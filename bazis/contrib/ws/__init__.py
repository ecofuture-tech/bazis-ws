try:
    from importlib.metadata import PackageNotFoundError, version
    __version__ = version('bazis-ws')
except PackageNotFoundError:
    __version__ = 'dev'


WS_PREFIX = 'user_ws:'
COMMON_CHANNEL = 'user_ws:common'
