"""Public Qt meta-object contract, independent of implementation class layout."""


def qt_contract(kind):
    meta = kind.staticMetaObject
    properties = {}
    for index in range(meta.propertyCount()):
        prop = meta.property(index)
        properties[prop.name()] = {
            "type": prop.typeName(), "writable": prop.isWritable(),
            "notify": bytes(prop.notifySignal().methodSignature()).decode(),
            "constant": prop.isConstant(),
        }
    methods = {}
    for index in range(meta.methodCount()):
        method = meta.method(index)
        name = bytes(method.methodSignature()).decode()
        if not name.startswith("_"):
            methods[name] = {"kind": method.methodType().name, "return": method.typeName()}
    return {"properties": properties, "methods": methods}
