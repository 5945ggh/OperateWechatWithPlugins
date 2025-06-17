from OWCP4b2 import PluginBase, MsgFilter, MsgType

class FilterSYS(MsgFilter):
    def execute(self, listen_object, msg):
        if msg.type == MsgType.SYS:
            return False
        return True

class FilterRecall(MsgFilter):
    def execute(self, listen_object, msg):
        if msg.type == MsgType.RECALL:
            return False
        return True

class FilterSelf(MsgFilter):
    def execute(self, listen_object, msg):
        if msg.type == MsgType.SELF:
            return False
        return True

class FilterTime(MsgFilter):
    def execute(self, listen_object, msg):
        if msg.type == MsgType.TIME:
            return False
        return True