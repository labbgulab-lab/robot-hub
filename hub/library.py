"""The lab's shared robot files: one GitHub release, assets named per robot.

Files are too big for git (a built Furhat skill is 85 MB), so they live as
assets of a release on the hub's own private repo. Every lab member's hub
lists the same files, as far as their GitHub account can see the repo.

  asset name   <robot>__<file name>        furhat__OpenAIChat_1.3.0.skill
  asset label  what the uploader's hub found, e.g. "keyless; needs gpt"

Nothing reaches GitHub with a key in it: an upload goes through
`keyscrub.scrub()` first. A file whose key was removed has a key *slot*, and
a download can fill it with one of this hub's own keys (`keyscrub.inject`).

Auth: GITHUB_TOKEN from .env if set, else whatever `gh auth token` returns.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, AsyncIterator, Optional

import httpx

from . import keyscrub

log = logging.getLogger("hub.library")

DEFAULT_REPO = "labbgulab-lab/robot-hub"
TAG = "robot-files"
API = "https://api.github.com"
UPLOADS = "https://uploads.github.com"
SEP = "__"
# Keyless copies kept on this laptop: the lab's GitHub link ran at ~200 KB/s
# (2026-10-06), seven minutes per skill, so a second download -- the same file
# with a key this time -- must not fetch it again.
CACHE_KEEP = 4
MAX_BYTES = 2_000_000_000          # GitHub's per-asset limit is 2 GiB

# The library's robots. Its own list, not the adapters': Pepper has files
# (and a card photo) before it has an adapter.
ROBOTS = {
    "furhat": "Furhat",
    "reachy_wireless": "Reachy Mini",
    "reachy_lite": "Reachy Mini Lite",
    "nao": "NAO",
    "pepper": "Pepper",
}

NO_SIGN_IN = ("uploading needs a GitHub sign-in with write access to the repo -- "
              "run `gh auth login`, or put GITHUB_TOKEN=... in robot-hub's .env")

_NEEDS = re.compile(r"needs ([a-z,]+)")


class LibraryError(RuntimeError):
    """Something the person at the page can act on; str() says what."""


def safe_name(name: str) -> str:
    """GitHub rewrites odd characters in asset names on its own; doing it here
    keeps the name the page shows equal to the one stored."""
    name = Path(name).name.strip()
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    if not name:
        raise LibraryError("that file has no usable name")
    return name


def asset_name(robot: str, name: str) -> str:
    return "{}{}{}".format(robot, SEP, safe_name(name))


def _public(asset: dict[str, Any]) -> Optional[dict[str, Any]]:
    robot, sep, name = asset["name"].partition(SEP)
    if not sep or robot not in ROBOTS:
        return None
    label = asset.get("label") or ""
    m = _NEEDS.search(label)
    return {
        "id": asset["id"],
        "robot": robot,
        "name": name,
        "size": asset.get("size", 0),
        "updated": asset.get("updated_at"),
        "uploader": (asset.get("uploader") or {}).get("login", ""),
        "needs": m.group(1).split(",") if m else [],
        "keyless": "keyless" in label,
    }


class Library:
    def __init__(self, config: Any, keys: Any, bus: Any = None) -> None:
        self.config = config
        self.keys = keys
        self.bus = bus
        self.repo = config.secret("ROBOT_FILES_REPO") or DEFAULT_REPO
        self._token: Optional[str] = None
        self._token_missing_since = 0.0
        self._release: Optional[dict[str, Any]] = None
        self.workdir = Path(tempfile.gettempdir()) / "robot-hub-files"

    # ------------------------------------------------------------- GitHub
    def _get_token(self) -> str:
        if self._token:
            return self._token
        if self._token_missing_since and time.monotonic() - self._token_missing_since < 60:
            raise LibraryError(NO_SIGN_IN)      # don't run gh on every request
        token = self.config.secret("GITHUB_TOKEN")
        if not token:
            try:
                token = subprocess.run(
                    ["gh", "auth", "token"], capture_output=True, text=True,
                    timeout=10).stdout.strip()
            except (OSError, subprocess.SubprocessError):
                token = ""
        if not token:
            self._token_missing_since = time.monotonic()
            raise LibraryError(NO_SIGN_IN)
        self._token = token
        return token

    def _headers(self, need_auth: bool = True) -> dict[str, str]:
        """Reading the library needs no sign-in while the repo is public, so
        a lab member without GitHub set up can still list and download.
        Uploading and deleting always need one."""
        headers = {"Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28"}
        try:
            headers["Authorization"] = "Bearer " + self._get_token()
        except LibraryError:
            if need_auth:
                raise
        return headers

    def _client(self, timeout: float = 30.0) -> httpx.AsyncClient:
        # Downloads redirect to a storage host; httpx drops the Authorization
        # header when a redirect leaves the origin, which is what GitHub wants.
        return httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=15.0),
                                 follow_redirects=True)

    def _explain(self, res: httpx.Response, doing: str) -> LibraryError:
        if res.status_code in (401, 403) and "rate limit" not in res.text.lower():
            self._token = None
            return LibraryError("GitHub refused this laptop's sign-in while {} "
                                "-- run `gh auth login` again".format(doing))
        if res.status_code == 404:
            return LibraryError(
                "this GitHub account cannot see {} -- ask for access to the "
                "repo, or sign in with the lab account".format(self.repo))
        try:
            message = res.json().get("message", "")
        except ValueError:
            message = res.text[:200]
        return LibraryError("GitHub said {} while {}: {}".format(
            res.status_code, doing, message))

    async def _get_release(self, client: httpx.AsyncClient, create: bool) -> Optional[dict]:
        if self._release is not None:
            return self._release
        res = await client.get("{}/repos/{}/releases/tags/{}".format(API, self.repo, TAG),
                               headers=self._headers(need_auth=False))
        if res.status_code == 200:
            self._release = res.json()
            return self._release
        if res.status_code != 404:
            raise self._explain(res, "opening the file library")
        repo = await client.get("{}/repos/{}".format(API, self.repo),
                                headers=self._headers(need_auth=False))
        if repo.status_code != 200:
            raise self._explain(repo, "opening the file library")
        if not create:
            return None             # the repo is there; nothing uploaded yet
        res = await client.post(
            "{}/repos/{}/releases".format(API, self.repo), headers=self._headers(),
            json={"tag_name": TAG, "name": "Robot files",
                  "body": "Shared robot files (skills, apps, configs), managed by "
                          "the Robot Hub's Files panel. Keys are removed before "
                          "upload; download through the hub to get a copy with "
                          "your own key.",
                  "make_latest": "false"})
        if res.status_code not in (200, 201):
            raise self._explain(res, "creating the file library")
        self._release = res.json()
        return self._release

    async def _assets(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        release = await self._get_release(client, create=False)
        if release is None:
            return []
        out, page = [], 1
        while True:
            res = await client.get(
                "{}/repos/{}/releases/{}/assets".format(API, self.repo, release["id"]),
                headers=self._headers(need_auth=False), params={"per_page": 100, "page": page})
            if res.status_code != 200:
                raise self._explain(res, "listing the files")
            batch = res.json()
            out += batch
            if len(batch) < 100:
                return out
            page += 1

    # ---------------------------------------------------------------- API
    async def listing(self) -> dict[str, Any]:
        async with self._client() as client:
            assets = await self._assets(client)
        files = [f for f in (_public(a) for a in assets) if f]
        files.sort(key=lambda f: (f["robot"], f["name"].lower()))
        return {"ok": True, "repo": self.repo,
                "robots": [{"id": k, "label": v} for k, v in ROBOTS.items()],
                "files": files}

    async def upload(self, robot: str, name: str, source: Path,
                     replace: bool = False) -> dict[str, Any]:
        if robot not in ROBOTS:
            raise LibraryError("unknown robot {!r}".format(robot))
        target = asset_name(robot, name)
        work = Path(tempfile.mkdtemp(dir=self._ensure_workdir()))
        try:
            started = time.monotonic()
            secrets = keyscrub.known_secrets(k["key"] for k in self.keys.all_secrets())
            try:
                result = await asyncio.to_thread(keyscrub.scrub, source, work, secrets)
            except keyscrub.KeyFound as exc:
                raise LibraryError(str(exc)) from exc
            except Exception as exc:  # noqa: BLE001  (a corrupt archive, say)
                raise LibraryError("could not read {}: {}".format(name, exc)) from exc
            if result.removed:
                self._log("info", "Files: removed {} from {} before upload".format(
                    ", ".join(result.removed), name))
            providers = sorted({s.provider for s in result.slots})
            label = "keyless" + ("; needs {}".format(",".join(providers)) if providers else "")

            async with self._client(timeout=900.0) as client:
                release = await self._get_release(client, create=True)
                existing = next((a for a in await self._assets(client)
                                 if a["name"] == target), None)
                if existing is not None:
                    if not replace:
                        return {"ok": False, "exists": True,
                                "error": "{} already has a file called {}".format(
                                    ROBOTS[robot], safe_name(name))}
                    res = await client.delete(
                        "{}/repos/{}/releases/assets/{}".format(API, self.repo, existing["id"]),
                        headers=self._headers())
                    if res.status_code not in (204, 404):
                        raise self._explain(res, "replacing the old copy")
                size = result.path.stat().st_size
                headers = {**self._headers(), "Content-Type": "application/octet-stream",
                           "Content-Length": str(size)}
                res = await client.post(
                    "{}/repos/{}/releases/{}/assets".format(UPLOADS, self.repo, release["id"]),
                    params={"name": target, "label": label}, headers=headers,
                    content=_read_chunks(result.path))
                if res.status_code not in (200, 201):
                    raise self._explain(res, "uploading {}".format(name))
            item = _public(res.json())
            if item is not None:        # the uploader's own download is instant
                await asyncio.to_thread(shutil.copyfile, result.path,
                                        self._cache_path(item["id"], item["size"], item["name"]))
                self._prune_cache()
            self._log("ok", "Files: {} uploaded for {} ({:.0f} s, {})".format(
                safe_name(name), ROBOTS[robot], time.monotonic() - started,
                "key removed" if result.removed else "no key in it"))
            return {"ok": True, "file": item, "removed": result.removed}
        finally:
            shutil.rmtree(work, ignore_errors=True)

    async def delete(self, asset_id: int) -> dict[str, Any]:
        async with self._client() as client:
            res = await client.delete(
                "{}/repos/{}/releases/assets/{}".format(API, self.repo, asset_id),
                headers=self._headers())
        if res.status_code not in (204, 404):
            raise self._explain(res, "deleting the file")
        self._log("info", "Files: deleted a file from the library")
        return {"ok": True}

    async def fetch(self, asset_id: int, key_id: Optional[str]) -> tuple[Path, str, Path]:
        """Download one file to a temp folder; with `key_id`, put that hub key
        into the file's key slots. Returns (file, download name, folder to
        remove once sent)."""
        work = Path(tempfile.mkdtemp(dir=self._ensure_workdir()))
        try:
            async with self._client(timeout=900.0) as client:
                meta = await client.get(
                    "{}/repos/{}/releases/assets/{}".format(API, self.repo, asset_id),
                    headers=self._headers(need_auth=False))
                if meta.status_code != 200:
                    raise self._explain(meta, "finding the file")
                item = _public(meta.json())
                name = item["name"] if item else meta.json()["name"]
                # Keyless as stored, so safe to keep; the asset id changes
                # when a file is replaced, and the size guards a cut transfer.
                raw = self._cache_path(asset_id, meta.json().get("size", -1), name)
                if not raw.is_file():
                    part = work / ("part-" + name)
                    headers = {**self._headers(need_auth=False), "Accept": "application/octet-stream"}
                    async with client.stream(
                            "GET", "{}/repos/{}/releases/assets/{}".format(API, self.repo, asset_id),
                            headers=headers) as res:
                        if res.status_code != 200:
                            await res.aread()
                            raise self._explain(res, "downloading {}".format(name))
                        with part.open("wb") as fh:
                            async for chunk in res.aiter_bytes(1 << 20):
                                fh.write(chunk)
                    if part.stat().st_size != meta.json().get("size", -1):
                        raise LibraryError("the download of {} was cut short -- "
                                           "try again".format(name))
                    part.replace(raw)
                    self._prune_cache()
            if not key_id:
                return raw, name, work
            entry = self.keys.get(key_id)
            if entry is None:
                raise LibraryError("that key is no longer in the hub")
            out = work / name
            filled = await asyncio.to_thread(
                keyscrub.inject, raw, out, entry["provider"], entry["key"])
            if not filled:
                raise LibraryError("{} has no place for a {} key".format(
                    name, entry["provider"]))
            self._log("info", "Files: {} downloaded with the key “{}” in it "
                      "— keep that copy to yourself".format(name, entry["label"]))
            return out, name, work
        except BaseException:
            shutil.rmtree(work, ignore_errors=True)
            raise

    # ------------------------------------------------------------ helpers
    def _ensure_workdir(self) -> Path:
        self.workdir.mkdir(parents=True, exist_ok=True)
        return self.workdir

    def _cache_path(self, asset_id: int, size: int, name: str) -> Path:
        cache = self._ensure_workdir() / "cache"
        cache.mkdir(exist_ok=True)
        return cache / "{}-{}-{}".format(asset_id, size, name)

    def _prune_cache(self) -> None:
        files = sorted((self._ensure_workdir() / "cache").glob("*"),
                       key=lambda f: f.stat().st_mtime, reverse=True)
        for old in files[CACHE_KEEP:]:
            try:
                old.unlink()
            except OSError:
                pass            # being sent right now; next prune gets it

    def _log(self, level: str, text: str) -> None:
        if self.bus is not None:
            self.bus.emit_log(level, text)
        else:
            log.info(text)


async def _read_chunks(path: Path, size: int = 1 << 20) -> AsyncIterator[bytes]:
    with path.open("rb") as fh:
        while True:
            chunk = await asyncio.to_thread(fh.read, size)
            if not chunk:
                return
            yield chunk
