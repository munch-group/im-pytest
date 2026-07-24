"""The notebook front door: the ``check()`` function and the ``%%test`` magic,
rendered as an anywidget styled like ``script-widget``'s ``%%exercise`` output.

The widget has up to two cards:

* **Checks** — one ✓/✗ row per tested function, with the failing assertion, a
  "not defined yet" note, and a summary line.
* **Terminal output** — shown only when the student's code printed something or
  raised a non-assertion error; it shows their prints and a colored traceback,
  exactly like the ``%%exercise`` widget.
"""
from __future__ import annotations

import io
import linecache
import types
from contextlib import redirect_stdout, redirect_stderr

import anywidget
import traitlets

from .report import Report, PASS, FAIL, ERROR
from .resources import resolve_test
from .runner import run, run_injected, format_traceback

try:
    from IPython import get_ipython
    from IPython.display import display as _ipy_display
except Exception:  # pragma: no cover
    def get_ipython():
        return None

    def _ipy_display(*a, **k):
        pass


__all__ = ["TestResultWidget", "check", "register_test_magic"]


_ESM = r"""
const ANSI_16 = [
  "#3e424d","#e75c58","#00a250","#ddb62b","#208ffb","#d160c4","#60c6c8","#c5c1b4",
  "#282c36","#b22b31","#007427","#b27d12","#0065ca","#a03196","#258f8f","#a1a6b2"];
function rgbToHex(r,g,b){return "#"+[r,g,b].map(v=>v.toString(16).padStart(2,"0")).join("");}
function xterm256(n){
  if(n<16)return ANSI_16[n];
  if(n<232){n-=16;const L=[0,95,135,175,215,255];return rgbToHex(L[Math.floor(n/36)],L[Math.floor((n%36)/6)],L[n%6]);}
  const g=8+(n-232)*10;return rgbToHex(g,g,g);}
function applySGR(s,c){for(let i=0;i<c.length;i++){const k=c[i];
  if(k===0){s.fg=s.bg=null;s.bold=s.italic=s.underline=false;}
  else if(k===1)s.bold=true;else if(k===22)s.bold=false;
  else if(k===3)s.italic=true;else if(k===23)s.italic=false;
  else if(k===4)s.underline=true;else if(k===24)s.underline=false;
  else if(k===39)s.fg=null;else if(k===49)s.bg=null;
  else if(k>=30&&k<=37)s.fg=ANSI_16[k-30];else if(k>=90&&k<=97)s.fg=ANSI_16[8+k-90];
  else if(k>=40&&k<=47)s.bg=ANSI_16[k-40];else if(k>=100&&k<=107)s.bg=ANSI_16[8+k-100];
  else if(k===38||k===48){const m=c[i+1];let col=null;
    if(m===5){col=xterm256(c[i+2]);i+=2;}else if(m===2){col=rgbToHex(c[i+2],c[i+3],c[i+4]);i+=4;}
    if(k===38)s.fg=col;else s.bg=col;}}}
function ansiToHtml(text){
  const frag=document.createDocumentFragment();
  const s={fg:null,bg:null,bold:false,italic:false,underline:false};
  const re=/\x1b\[([0-9;]*)m/g;let last=0,m;
  function flush(chunk){if(!chunk)return;
    if(s.fg||s.bg||s.bold||s.italic||s.underline){const sp=document.createElement("span");
      if(s.fg)sp.style.color=s.fg;if(s.bg)sp.style.backgroundColor=s.bg;
      if(s.bold)sp.style.fontWeight="bold";if(s.italic)sp.style.fontStyle="italic";
      if(s.underline)sp.style.textDecoration="underline";sp.textContent=chunk;frag.appendChild(sp);}
    else frag.appendChild(document.createTextNode(chunk));}
  while((m=re.exec(text))!==null){flush(text.slice(last,m.index));last=re.lastIndex;
    applySGR(s,m[1].length?m[1].split(";").map(Number):[0]);}
  flush(text.slice(last));return frag;}

function fillAncestors(el){let a=el;for(let i=0;i<4&&a;i++){a.style.width="100%";a.style.boxSizing="border-box";a=a.parentElement;}}

function card(title){
  const root=document.createElement("div");root.className="imp-root";
  const h=document.createElement("div");h.className="imp-header";h.textContent=title;root.appendChild(h);
  const body=document.createElement("div");body.className="imp-body";root.appendChild(body);
  return {root, body};
}

function render({model, el}){
  fillAncestors(el);
  const wrap=document.createElement("div");

  // ---- checks card ----
  const project=model.get("project")||"tests";
  const {root, body}=card("Checks — "+project);
  (model.get("results")||[]).forEach(r=>{
    const row=document.createElement("div");row.className="imp-row";
    const mark=document.createElement("span");
    mark.className="imp-mark "+(r.status==="pass"?"imp-ok":"imp-bad");
    mark.textContent=r.status==="pass"?"✓":"✗";
    const nm=document.createElement("span");nm.className="imp-name"+(r.status==="pass"?"":" imp-name-bad");nm.textContent=r.name;
    row.appendChild(mark);row.appendChild(nm);body.appendChild(row);
    if(r.status!=="pass"&&r.message){const msg=document.createElement("pre");msg.className="imp-msg";msg.textContent=r.message;body.appendChild(msg);}
  });
  const undef=model.get("undefined")||[];
  if(undef.length){
    const b=document.createElement("div");b.className="imp-undef";
    const t=document.createElement("b");t.textContent="Not defined yet: ";b.appendChild(t);
    b.appendChild(document.createTextNode(undef.join(", ")));
    const note=document.createElement("div");note.className="imp-undef-note";
    note.textContent="These are misspelled or not written yet — their checks were skipped.";
    b.appendChild(note);body.appendChild(b);
  }
  const summary=document.createElement("div");
  summary.className="imp-summary "+(model.get("ok")?"imp-ok":"imp-bad");
  summary.textContent=model.get("summary")||"";
  body.appendChild(summary);
  wrap.appendChild(root);

  // ---- terminal-output card (like %%exercise) ----
  const stdout=model.get("stdout")||"";
  const tb=model.get("traceback")||"";
  if(stdout||tb){
    const term=card("Terminal output:");
    if(stdout){const pre=document.createElement("pre");pre.className="imp-term";pre.appendChild(ansiToHtml(stdout));term.body.appendChild(pre);}
    if(tb){const pre=document.createElement("pre");pre.className="imp-term imp-tb";pre.appendChild(ansiToHtml(tb));term.body.appendChild(pre);}
    wrap.appendChild(term.root);
  }
  el.appendChild(wrap);
}
export default { render };
"""

_CSS = r"""
.imp-root { width:100%; box-sizing:border-box; margin-top:8px;
  font-family:system-ui,-apple-system,"Segoe UI",sans-serif;
  background:#f3f4f6; border-radius:6px; padding:8px; border:1px solid #9ca3af; }
.imp-root + .imp-root { margin-top:10px; }
.imp-header { font-size:11.5px; font-weight:600; letter-spacing:.02em; color:#6b7280;
  text-transform:uppercase; margin:2px 4px 6px; }
.imp-body { background:#ffffff; border-radius:4px; padding:10px 14px; }
.imp-row { display:flex; gap:8px; align-items:baseline; padding:2px 0; }
.imp-mark { font-weight:700; }
.imp-ok { color:#1f7a68; }
.imp-bad { color:#b23b3b; }
.imp-name { color:#26313f; }
.imp-name-bad { color:#26313f; font-weight:600; }
.imp-msg { margin:2px 0 6px 22px; font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
  font-size:12.5px; line-height:18px; white-space:pre-wrap; word-break:break-word; color:#7a2e2e; }
.imp-undef { margin:6px 0 2px; border-left:4px solid #b26a1f; background:#fbf1e2;
  border-radius:6px; padding:8px 12px; color:#5a6675; font-size:13px; }
.imp-undef b { color:#b26a1f; }
.imp-undef-note { margin-top:4px; font-size:12px; }
.imp-summary { margin-top:10px; padding-top:8px; border-top:1px solid #eee; font-weight:600; }
.imp-term { margin:0; font-family:ui-monospace,SFMono-Regular,"Cascadia Code",Menlo,monospace;
  font-size:12.5px; line-height:18px; white-space:pre-wrap; word-break:break-word; color:#24292f; }
.imp-body > .imp-term + .imp-term { margin-top:8px; }
"""


class TestResultWidget(anywidget.AnyWidget):
    _esm = _ESM
    _css = _CSS

    project = traitlets.Unicode("").tag(sync=True)
    results = traitlets.List(traitlets.Dict()).tag(sync=True)
    undefined = traitlets.List(traitlets.Unicode()).tag(sync=True)
    summary = traitlets.Unicode("").tag(sync=True)
    ok = traitlets.Bool(True).tag(sync=True)
    stdout = traitlets.Unicode("").tag(sync=True)
    traceback = traitlets.Unicode("").tag(sync=True)

    def __init__(self, report: Report):
        super().__init__()
        self.layout.width = "100%"
        self.project = report.project
        if report.import_error is not None:
            self.results = [{"name": report.import_error, "status": ERROR,
                             "message": "Your code could not be run — see the terminal output below."}]
            self.summary = "Fix the error below, then run the checks again."
            self.ok = False
        else:
            self.results = [{"name": o.name, "status": o.status, "message": o.message}
                            for o in report.outcomes]
            if report.ok:
                self.summary = f"All {report.passed} checks passed — nice work!"
            else:
                bits = f"{report.passed} passed, {report.failed} to fix"
                if report.undefined:
                    bits += f", {len(report.undefined)} not defined"
                self.summary = bits
            self.ok = report.ok
        self.undefined = list(report.undefined)
        self.stdout = report.stdout
        self.traceback = report.traceback


def _show(report: Report):
    ip = get_ipython()
    if ip is not None:
        try:
            _ipy_display(TestResultWidget(report))
            return report
        except Exception:  # pragma: no cover
            pass
    print(report.to_text())
    return report


def check(project: str, *, tests: str | None = None, failfast: bool = True):
    """Test the student's ``<project>.py`` in the working folder.

    >>> check("translationproject")
    """
    test_path = tests or resolve_test(project)
    return _show(run(test_path, project=project, failfast=failfast))


def register_test_magic(ipython=None):
    """Register the ``%%test <project>`` cell magic (idempotent)."""
    try:
        from IPython.core.magic import register_cell_magic  # noqa: F401
    except Exception:
        return
    ip = ipython or get_ipython()
    if ip is None:
        return

    def test(line, cell):
        project = line.strip().split()[0] if line.strip() else ""
        if not project:
            print("Usage: %%test <projectname>")
            return
        test_path = resolve_test(project)
        filename = f"<{project}>"
        module = types.ModuleType(project)
        module.__file__ = filename
        # register the cell source so tracebacks can show the offending line
        linecache.cache[filename] = (len(cell), None, cell.splitlines(keepends=True), filename)
        buf = io.StringIO()
        try:
            code = compile(cell, filename, "exec")
            with redirect_stdout(buf), redirect_stderr(buf):
                exec(code, module.__dict__)
        except Exception as exc:  # noqa: BLE001
            rep = Report(project=project,
                         import_error=f"{type(exc).__name__}: {exc}",
                         traceback=format_traceback(type(exc), exc, exc.__traceback__, filename),
                         stdout=buf.getvalue().rstrip("\n"))
            return _show(rep)
        rep = run_injected(project, module, test_path, pre_stdout=buf.getvalue())
        ip.user_ns.update({k: v for k, v in module.__dict__.items() if not k.startswith("__")})
        return _show(rep)

    ip.register_magic_function(test, magic_kind="cell", magic_name="test")
