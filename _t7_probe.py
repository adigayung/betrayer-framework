"""Temporary probe (Task 07): lifecycle path for modules/extensions."""
from betrayer import Bootstrap
from betrayer.core.module import Module
from betrayer.core.extension import Extension


class ProbeModule(Module):
    name = "probe_mod"

    def register(self, context):
        print("mod.register:", type(context).__name__)

    def initialize(self, context):
        print("mod.initialize:", type(context).__name__, hasattr(context, "container"))

    def shutdown(self, context):
        print("mod.shutdown:", type(context).__name__)


class ProbeExtension(Extension):
    name = "probe_ext"
    version = "0.1.0"

    def register(self, context):
        print("ext.register:", type(context).__name__)


app = Bootstrap(name="probe").build()
app.modules.register(ProbeModule())
app.extensions.register(ProbeExtension())
print("modreg:", sorted(n for n in dir(app.modules) if not n.startswith("_")))
print("extreg:", sorted(n for n in dir(app.extensions) if not n.startswith("_")))
print("core:", sorted(n for n in dir(app.core) if not n.startswith("_")))
for step in ("initialize", "run", "shutdown"):
    try:
        getattr(app, step)()
        print(step, "OK state=", app.state)
    except Exception as exc:
        print(step, "FAILED", type(exc).__name__, exc)
