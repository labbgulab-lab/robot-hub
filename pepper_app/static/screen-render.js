/* Draws one screen item. Used by the tablet page (screen.html) and by the
   dashboard's "On Pepper's screen" preview, so the preview is what people see.

   ES5 only: Pepper's tablet runs an old Android WebView. Sizes are in em and
   1em is set to 1% of the box width, so the same drawing fits the 1280x800
   tablet and the small preview. */
var PepperScreen = (function () {
  var CSS =
    '.ps{position:relative;width:100%;height:100%;overflow:hidden;font-family:Roboto,"Segoe UI",Arial,sans-serif;' +
    'background:#fff;color:#1e293b;-webkit-user-select:none;user-select:none;box-sizing:border-box}' +
    '.ps *{box-sizing:border-box}' +
    '.ps-center{position:absolute;top:0;left:0;right:0;bottom:0;display:-webkit-box;display:-webkit-flex;display:flex;' +
    '-webkit-flex-direction:column;flex-direction:column;-webkit-align-items:center;align-items:center;' +
    '-webkit-justify-content:center;justify-content:center;text-align:center;padding:3em}' +
    '.ps-welcome{background:-webkit-linear-gradient(135deg,#e0f2fe,#e0e7ff);background:linear-gradient(135deg,#e0f2fe,#e0e7ff);color:#312e81}' +
    '.ps-h1{font-size:6em;font-weight:700}' +
    '.ps-big{font-size:11em;line-height:1.1}' +
    '.ps-emoji{font-size:15em;line-height:1.05}' +
    '.ps-grid{position:absolute;top:0;left:0;right:0;bottom:0;padding:1.5em;overflow:hidden}' +
    '.ps-cell{float:left;width:11.1%;height:16%;text-align:center;border:1px solid #e2e8f0;position:relative}' +
    '.ps-cell b{position:absolute;left:.4em;top:.2em;font-size:1.6em;color:#64748b;font-weight:600}' +
    '.ps-cell span{font-size:6em;line-height:1.6}' +
    '.ps-sub{font-size:2.4em;opacity:.7;margin-top:.4em}' +
    '.ps-msg{font-size:4.2em;font-weight:600;line-height:1.25;margin-top:.3em;max-width:90%}' +
    '.ps-choice{position:absolute;top:0;left:0;right:0;bottom:0;padding:2.5em 2.5em 12em;display:-webkit-box;display:-webkit-flex;display:flex;' +
    '-webkit-flex-direction:column;flex-direction:column}' +
    '.ps-q{text-align:center;font-weight:700;font-size:3.8em;margin-bottom:.5em}' +
    '.ps-opts{-webkit-box-flex:1;-webkit-flex:1;flex:1;display:-webkit-box;display:-webkit-flex;display:flex}' +
    '.ps-opt{-webkit-box-flex:1;-webkit-flex:1;flex:1;margin:0 1.2em;border-radius:1.6em;border:.6em solid transparent;' +
    'display:-webkit-box;display:-webkit-flex;display:flex;-webkit-flex-direction:column;flex-direction:column;' +
    '-webkit-align-items:center;align-items:center;-webkit-justify-content:center;justify-content:center;cursor:pointer;overflow:hidden}' +
    '.ps-opt:first-child{margin-left:0}.ps-opt:last-child{margin-right:0}' +
    '.ps-opt.picked{border-color:#16a34a;box-shadow:0 0 0 .9em rgba(22,163,74,.25)}' +
    '.ps-opt.dim{opacity:.45}' +
    '.ps-img{max-width:90%;max-height:65%;border-radius:1em;-o-object-fit:contain;object-fit:contain}' +
    '.ps-label{font-size:3.6em;font-weight:700;margin-top:.25em;text-align:center;padding:0 .4em}' +
    '.ps-label.big{font-size:6em;margin-top:0}' +
    '.ps-c0{background:#fef3c7;color:#78350f}.ps-c1{background:#ede9fe;color:#4c1d95}' +
    '.ps-c2{background:#dcfce7;color:#14532d}.ps-c3{background:#fee2e2;color:#7f1d1d}' +
    '.ps-slide{position:absolute;top:0;left:0;right:0;bottom:0;background:#000}' +
    '.ps-slide img{width:100%;height:100%;-o-object-fit:contain;object-fit:contain}' +
    '.ps-blank{position:absolute;top:0;left:0;right:0;bottom:0;background:#000}' +
    // The lab logo, bottom centre on every page but blank, slides and the emoji test
    // (Tomer chose it from data/logo-preview/preview.html, 2026-10-12). Taps pass through.
    '.ps-logo{position:absolute;left:50%;bottom:.9em;-webkit-transform:translateX(-50%);transform:translateX(-50%);' +
    'background:#fff;border-radius:1em;padding:.4em .9em;box-shadow:0 .1em .5em rgba(0,0,0,.15);pointer-events:none}' +
    '.ps-logo img{display:block;height:9.1em;width:auto}';   // 75% bigger than 5.2em (Tomer, 2026-10-12)
  var LOGO = '<div class="ps-logo"><img src="/screen/logo.png" alt=""></div>';

  function addCss() {
    if (document.getElementById('ps-css')) return;
    var s = document.createElement('style');
    s.id = 'ps-css';
    s.appendChild(document.createTextNode(CSS));
    document.head.appendChild(s);
  }

  function esc(t) {
    return String(t == null ? '' : t).replace(/[&<>"']/g, function (c) {
      return {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c];
    });
  }

  function html(state) {
    var it = (state && state.item) || {kind: 'welcome'};
    var k = it.kind;
    var page = body(state, it);
    return (k === 'blank' || k === 'slide' || k === 'emoji_test') ? page : page + LOGO;
  }

  function body(state, it) {
    var k = it.kind;
    if (k === 'blank') return '<div class="ps-blank"></div>';
    if (k === 'slide') return '<div class="ps-slide"><img src="' + esc(it.image) + '" alt=""></div>';
    if (k === 'message')
      return '<div class="ps-center ps-welcome">' + (it.emoji ? '<div class="ps-big">' + esc(it.emoji) + '</div>' : '') +
             '<div class="ps-msg" dir="auto">' + esc(it.text) + '</div></div>';
    if (k === 'emoji_test') {
      // Numbered, so the operator can say which ones show as empty boxes.
      var cells = it.cells || [], g = '';
      for (var j = 0; j < cells.length; j++)
        g += '<div class="ps-cell"><b>' + esc(cells[j][0]) + '</b><span>' + esc(cells[j][1]) + '</span></div>';
      return '<div class="ps-grid">' + g + '</div>';
    }
    if (k === 'choice') {
      var o = it.options || [], out = '';
      for (var i = 0; i < o.length; i++) {
        var cls = 'ps-opt ps-c' + (i % 4);
        if (state.picked) cls += state.picked === o[i].label ? ' picked' : ' dim';
        // A picture when one was uploaded, else the emoji (experiences "with emoji"),
        // else the word itself, big.
        var pic = o[i].image ? '<img class="ps-img" src="' + esc(o[i].image) + '" alt="">'
                             : (o[i].emoji ? '<div class="ps-emoji">' + esc(o[i].emoji) + '</div>' : '');
        out += '<div class="' + cls + '" data-i="' + i + '">' + pic +
               '<div class="ps-label' + (pic ? '' : ' big') + '" dir="auto">' + esc(o[i].label) + '</div></div>';
      }
      return '<div class="ps-choice"><div class="ps-q" dir="auto">' + esc(it.question) + '</div>' +
             '<div class="ps-opts">' + out + '</div></div>';
    }
    return '<div class="ps-center ps-welcome">' +
           '<div class="ps-h1">Hi, I\'m Pepper!</div><div class="ps-sub">Come closer and say hello</div></div>';
  }

  function fit(box) {
    var w = box.clientWidth || 1280;
    box.style.fontSize = (w / 100) + 'px';
  }

  /* render(box, state, onTap(index)) */
  function render(box, state, onTap) {
    addCss();
    fit(box);
    box.className = (box.className.replace(/\bps\b/g, '') + ' ps').replace(/^\s+/, '');
    box.innerHTML = html(state);
    var opts = box.querySelectorAll('.ps-opt');
    for (var i = 0; i < opts.length; i++) {
      (function (el) {
        el.onclick = function () { if (onTap) onTap(+el.getAttribute('data-i')); };
      })(opts[i]);
    }
  }

  return {render: render, fit: fit};
})();
