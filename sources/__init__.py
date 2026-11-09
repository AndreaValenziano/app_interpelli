from .istruzionebat_html import IstruzioneBatHtmlSource
from .scuolainterpelli_rss import ScuolaInterppelliRssSource
from .argo_albo import ArgoAlboSource
from .nuvola_albo import NuvolaAlboSource
from .trasparenzascuole_albo import TrasparenzascuoleAlboSource
from .trasparenzascuole_mac import TrasparenzascuoleMacSource


def get_enabled_sources():
    return [
        # IstruzioneBatRssSource: feed fermo dal 12/02/2026, stessi interpelli della pagina HTML
        IstruzioneBatHtmlSource(),
        ScuolaInterppelliRssSource(),
        ArgoAlboSource(),
        NuvolaAlboSource(),
        TrasparenzascuoleAlboSource(),
        TrasparenzascuoleMacSource(),
    ]
