from collections import ChainMap


from confctl.utils.template import LazyTemplate


class Ctx(ChainMap):
    # Reference to the root context
    global_ctx: "Ctx"

    def __getattr__(self, name):
        try:
            val = self[name]
        except KeyError:
            raise AttributeError(name)

        if isinstance(val, LazyTemplate):
            val = str(val)
            self[name] = val
        return val
