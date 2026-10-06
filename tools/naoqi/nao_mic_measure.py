import paramiko, wave, math, struct, os, tempfile

HOST, REMOTE = "172.20.10.14", "/home/nao/mictest.wav"
LOCAL = os.path.join(tempfile.gettempdir(), "mictest.wav")

c = paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="nao", password="nao", timeout=10,
          allow_agent=False, look_for_keys=False)
sftp = c.open_sftp()
sftp.get(REMOTE, LOCAL)
size = os.path.getsize(LOCAL)
sftp.close(); c.close()
print("pulled %s  (%d bytes)" % (LOCAL, size))

w = wave.open(LOCAL, "rb")
ch, sw, sr, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
print("channels=%d  sampwidth=%d  rate=%d  frames=%d  duration=%.2fs"
      % (ch, sw, sr, n, n / float(sr)))
raw = w.readframes(n); w.close()

samples = struct.unpack("<%dh" % (len(raw) // 2), raw)
names = ["left", "right", "front", "rear"][:ch]
print("\n%-8s %10s %10s %10s   %s" % ("mic", "RMS", "peak", "dBFS", "verdict"))
for i, nm in enumerate(names):
    chan = samples[i::ch]
    if not chan:
        continue
    rms = math.sqrt(sum(float(s) * s for s in chan) / len(chan))
    peak = max(abs(s) for s in chan)
    db = 20 * math.log10(rms / 32768.0) if rms > 0 else -999
    if db > -45:   verdict = "LIVE - clear signal"
    elif db > -60: verdict = "faint"
    else:          verdict = "SILENT / dead"
    print("%-8s %10.1f %10d %10.1f   %s" % (nm, rms, peak, db, verdict))
