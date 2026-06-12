"""boxd — the box daemon: a box's entire API surface, in one process.

The controller (ui/controller) is the panel; this is the intelligence
behind it. One daemon per box (GH200, M4-local); the controller treats
localhost as just another box. Absorbs the comfort-ui Vite middleware
per docs/CONTRACT-INVENTORY.md, domain by domain, until vite is only a
bundler again.
"""

__version__ = "0.1.0"
