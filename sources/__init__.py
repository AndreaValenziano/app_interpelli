from .istruzionebat_rss import IstruzioneBatRssSource
from .istruzionebat_html import IstruzioneBatHtmlSource
from .scuolainterpelli_rss import ScuolaInterppelliRssSource
from .argo_albo import ArgoAlboSource
from .nuvola_albo import NuvolaAlboSource
from .trasparenzascuole_albo import TrasparenzascuoleAlboSource


def get_enabled_sources():
    return [
        IstruzioneBatRssSource(),
        IstruzioneBatHtmlSource(),
        ScuolaInterppelliRssSource(),
        ArgoAlboSource(),
        NuvolaAlboSource(),
        TrasparenzascuoleAlboSource(),
    ]
