import asyncio
import json
import os
import re
import time
from dataclasses import dataclass
from typing import Callable, Iterable, Optional, Union
from urllib.parse import urlparse

import httpx
from loguru import logger

try:
    from .consts import INST_FOLDER, Network, HOME_PATH, MirrorHeaders
except ImportError:
    from consts import INST_FOLDER, Network, HOME_PATH, MirrorHeaders

ENABLE_ASYNC = True
ENABLE_PATH_IN_DOMAINS = False
IGNORE_DOMAINS_WITH_PATHS = True
SLEEP_TIMEOUT_PER_GROUP = 3
SLEEP_TIMEOUT_PER_TIMEOUT = 3
SLEEP_TIMEOUT_PER_CHECK = 1
TIMEOUTS_MAX = 3


@dataclass
class BaseInstance:
    relative_filepath_without_ext: str
    
    parent = None
    domains_handle = None
    check_domain = False
    priority = 0
    
    def set_parent(self, par):
        self.parent = par
    
    def get_relative_without_ext(self):
        if self.parent is None:
            return self.relative_filepath_without_ext
        return "/".join((INST_FOLDER, self.parent.relative_filepath_without_ext, self.relative_filepath_without_ext))
    
    def get_filepath(self, extension=".json"):
        return os.path.join(HOME_PATH, self.get_relative_without_ext() + extension)
    
    def file_exists(self, extension=".json"):
        return os.path.exists(self.get_filepath())

    def makedirs(self):
        dirname = os.path.dirname(self.get_filepath())
        if not os.path.exists(dirname):
            os.makedirs(dirname)
    
    def save_as_json(self, obj):
        with open(self.get_filepath(".json"), mode="w+", encoding="utf-8") as f:
            json.dump(obj, f, indent=4)
    
    def load_from_json(self):
        with open(self.get_filepath(".json"), mode="r", encoding="utf-8") as f:
            return json.load(f)
    
    def save_list_as_txt(self, obj):
        to_save = "\n".join(obj)
        with open(self.get_filepath(".txt"), mode="w+", encoding="utf-8") as f:
            f.write(to_save)


class BaseDomainsGettter:
    def check_if_update(self, domains):
        if not self.inst.file_exists():
            return True
        domains_old = self.inst.load_from_json()
        return not (domains == domains_old)
    
    @staticmethod
    def check_domain(domain):
        try:
            httpx.head("https://" + domain)
            time.sleep(SLEEP_TIMEOUT_PER_CHECK)
            return True
        except:
            return False
    
    def update(self):
        self.inst.makedirs()
        domains = list(sorted(tuple(filter(lambda url: url not in (False, "", None), self.get_all_domains()))))
        if self.inst.domains_handle is not None:
            domains = self.inst.domains_handle(domains)
        if self.inst.check_domain:
            domains = list(filter(self.check_domain, domains))
        if self.check_if_update(domains):
            self.inst.save_as_json(domains)
            self.inst.save_list_as_txt(domains)
            return True
        return False

    async def async_update(self):
        self.inst.makedirs()
        domains = await self.async_get_all_domains()
        domains = list(sorted(tuple(filter(lambda url: url not in (False, "", None), domains))))
        if self.inst.domains_handle is not None:
            domains = self.inst.domains_handle(domains)
        if self.inst.check_domain:  # I even don't want to fix it... It's all to Piped... I love u, Piped
            domains = list(filter(lambda x: self.check_domain(x), domains))
        if self.check_if_update(domains):
            self.inst.save_as_json(domains)
            self.inst.save_list_as_txt(domains)
            return True
        return False


@dataclass
class RegexFromUrlInstance(BaseInstance):
    url: str
    regex_pattern: Union[str, Iterable]
    domains_handle: Callable = None
    regex_group: str = "domain"
    check_domain: bool = False
    
    def from_instance(self):
        return RegexFromUrl(self)
    
    def get_patterns_compiled(self):
        if isinstance(self.regex_pattern, str):
            return (re.compile(self.regex_pattern, flags=re.MULTILINE), )
        return tuple(map(lambda x: re.compile(x, flags=re.MULTILINE), self.regex_pattern))


class RegexFromUrl(BaseDomainsGettter):
    def __init__(self, instance: RegexFromUrlInstance) -> None:
        self.inst = instance
        super().__init__()
    
    @staticmethod
    def _get_match_and_other_text(text, pattern, index_from=0):
        match = pattern.search(text[index_from:])
        if match is None:
            return False
        return match, index_from+match.end()+1

    def get_all_domains_from_text(self, text):
        domain_list = list()
        index_from = 0
        for pattern in self.inst.get_patterns_compiled():
            for _ in range(len(pattern.findall(text))):
                res = self._get_match_and_other_text(text, pattern, index_from)
                if not res:
                    break
                match, index_from = res
                if (match_group := match.groupdict().get(self.inst.regex_group)) is not None:
                    domain_list.append(match_group)
        return domain_list
    
    def get_all_domains(self):
        text = httpx.get(self.inst.url).text
        domain_list = self.get_all_domains_from_text(text)
        return domain_list
    
    async def async_get_all_domains(self):
        async with httpx.AsyncClient() as client:
            resp = await client.get(self.inst.url)
            text = resp.text
        domain_list = self.get_all_domains_from_text(text)
        return domain_list


@dataclass
class RegexCroppedFromUrlInstance(RegexFromUrlInstance):
    crop_from: Optional[str] = None
    crop_to: Optional[str] = None
    
    def get_cropped(self, text):
        crop_from_i = text.index(self.crop_from)+len(self.crop_from) if self.crop_from is not None else 0
        crop_to_i = text[crop_from_i:].index(self.crop_to) + crop_from_i if self.crop_to is not None else len(text)
        return text[crop_from_i:crop_to_i]
    
    def from_instance(self):
        return RegexCroppedFromUrl(self)


class RegexCroppedFromUrl(RegexFromUrl):
    def __init__(self, instance: RegexCroppedFromUrlInstance) -> None:
        super().__init__(instance)
    
    def get_all_domains_from_text(self, text):
        text = self.inst.get_cropped(text)
        return super().get_all_domains_from_text(text)


@dataclass
class JustFromUrlInstance(BaseInstance):
    url: str
    
    def from_instance(self):
        return JustFromUrl(self)


class JustFromUrl(BaseDomainsGettter):
    def __init__(self, instance: JustFromUrlInstance) -> None:
        self.inst = instance
        super().__init__()
    
    def get_all_domains(self):
        raw = httpx.get(self.inst.url).text
        domain_list = raw.strip("\n").split("\n")
        return domain_list

    async def async_get_all_domains(self):
        async with httpx.AsyncClient() as client:
            resp = await client.get(self.inst.url)
            domain_list = resp.text.strip("\n").split("\n")
            return domain_list


@dataclass
class JSONUsingCallableInstance(BaseInstance):
    url: str
    json_handle: Callable
    
    def from_instance(self):
        return JSONUsingCallable(self)


class JSONUsingCallable(BaseDomainsGettter):
    def __init__(self, instance: JSONUsingCallableInstance) -> None:
        self.inst = instance
        super().__init__()
    
    def get_all_domains(self):
        resp = httpx.get(self.inst.url)
        raw = resp.json()
        result = self.inst.json_handle(raw)
        return result

    async def async_get_all_domains(self, _timeouts=0, _last_timeout=None):
        if _timeouts > TIMEOUTS_MAX:
            raise _last_timeout
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(self.inst.url)
            except httpx.ConnectTimeout as e:
                time.sleep(SLEEP_TIMEOUT_PER_TIMEOUT)
                return await self.async_get_all_domains(_timeouts=_timeouts+1, _last_timeout=e)
            raw = resp.json()
            result = self.inst.json_handle(raw)
            return result


@dataclass
class GetDomainsFromHeadersInstance(BaseInstance):
    main: BaseInstance
    header: str
    
    # TODO: support priority 
    priority = 1
    
    def from_instance(self):
        return GetDomainsFromHeaders(self)


class GetDomainsFromHeaders(BaseDomainsGettter):
    def __init__(self, instance: GetDomainsFromHeadersInstance) -> None:
        self.inst = instance
        super().__init__()
    
    def get_domain_from_header(self, domain):
        _domain = None
        try:
            resp = httpx.head("https://" + domain)
            _domain = get_domain_from_url(resp.headers[self.inst.header])
        except KeyError:
            return None
        except Exception as e:
            logger.warning("Sth wrong with " + domain)
            logger.warning("Error: " + str(type(e)))
            logger.warning(f"{self.inst.header} from {domain} skipped")
        return _domain

    async def async_get_domain_from_header(self, domain):
        _domain = None
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.head("https://" + domain)
            _domain = get_domain_from_url(resp.headers[self.inst.header])
        except KeyError:
            return None
        except Exception as e:
            logger.warning("Sth wrong with " + domain)
            logger.warning("Error: " + str(type(e)))
            logger.warning(f"{self.inst.header} from {domain} skipped")
        return _domain
        
    
    def get_all_domains(self):
        main_domains = self.inst.main.load_from_json()
        domains = list(filter(lambda x: x is not None, map(self.get_domain_from_header, main_domains)))
        return tuple(domains)
    
    async def async_get_all_domains(self):
        main_domains = self.inst.main.load_from_json()
        domains = list()
        for main in main_domains:
            domain = await self.async_get_domain_from_header(main)
            if domain:
                domains.append(domain)
        return tuple(domains)


@dataclass
class InstancesGroupData:
    name: str
    home_url: str
    relative_filepath_without_ext: str
    instances: Iterable
    description: str=None
    
    def get_desc(self):
        if self.description is None:
            return ""
        return self.description

    def get_name(self):
        return self.name.lower()
    
    def from_instance(self):
        return InstancesGroup(self, *self.instances)
    
    def get_relative_filepath(self):
        return "/".join((INST_FOLDER, self.relative_filepath_without_ext))
    
    def get_folderpath(self):
        return os.path.join(HOME_PATH, self.get_relative_filepath())


class InstancesGroup:
    def __init__(self, data: InstancesGroupData, *instances) -> None:
        self.relative_filepath_without_ext = data.relative_filepath_without_ext
        self.instances = list()
        self.inst = data
        for inst in instances:
            inst.set_parent(self)
            self.instances.append(inst)
    
    def update(self):
        for inst in self.instances:
            inst.from_instance().update()

    def get_coroutines(self):
        return tuple([x.from_instance().async_update() for x in self.instances])


def get_domain_from_url(url):
    parsed = urlparse(url)
    url_has_path = parsed.path not in ("", "/", None)
    if not url_has_path:
        return parsed.netloc
    elif url_has_path and IGNORE_DOMAINS_WITH_PATHS:
        return False
    if url_has_path and ENABLE_PATH_IN_DOMAINS:
        return parsed.netloc + parsed.path
    else:
        return parsed.netloc


INSTANCE_GROUPS = [
    InstancesGroupData(name="ProxiTok", home_url="https://github.com/pablouser1/ProxiTok", relative_filepath_without_ext="tiktok/proxitok",
                       instances=(RegexFromUrlInstance(relative_filepath_without_ext=Network.CLEARNET, url="https://raw.githubusercontent.com/wiki/pablouser1/ProxiTok/Public-instances.md", regex_pattern=r"\|\s+\[(?P<domain>[\w\-\.]+)\]\((?P<url>https?:\/\/[\w\-\.\/]+)\)\s+(?:\(Official\)\s+)?\|\s+(?P<cloudflare>Yes|No)\s+\|\s+(?P<flagemoji>\S+)\s+\|"),
                                  RegexFromUrlInstance(relative_filepath_without_ext=Network.ONION, url="https://raw.githubusercontent.com/wiki/pablouser1/ProxiTok/Public-instances.md", regex_pattern=r"\|\s+\[(?P<domain>[\w\-\.]+\.onion)\]\((?P<url>https?:\/\/[\w\-\.\/]+)\)\s+\|"),
                                  RegexFromUrlInstance(relative_filepath_without_ext=Network.I2P, url="https://raw.githubusercontent.com/wiki/pablouser1/ProxiTok/Public-instances.md", regex_pattern=r"\|\s+\[(?P<domain>[\w\-\.]+\.i2p)\]\((?P<url>https?:\/\/[\w\-\.\/]+)\)\s+\|"))),
    InstancesGroupData(name="SimplyTranslate", home_url="https://simple-web.org/projects/simplytranslate.html", relative_filepath_without_ext="translate/simplytranslate",
                       instances=(JustFromUrlInstance(relative_filepath_without_ext=Network.CLEARNET, url="https://simple-web.org/instances/simplytranslate"),
                                  JustFromUrlInstance(relative_filepath_without_ext=Network.ONION, url="https://simple-web.org/instances/simplytranslate_onion"),
                                  JustFromUrlInstance(relative_filepath_without_ext=Network.I2P, url="https://simple-web.org/instances/simplytranslate_i2p"),
                                  JustFromUrlInstance(relative_filepath_without_ext=Network.LOKI, url="https://simple-web.org/instances/simplytranslate_loki"))),
    InstancesGroupData(name="LingvaTranslate", home_url="https://github.com/TheDavidDelta/lingva-translate#lingva-translate", relative_filepath_without_ext="translate/lingvatranslate",
                       instances=(RegexFromUrlInstance(relative_filepath_without_ext=Network.CLEARNET, url="https://raw.githubusercontent.com/thedaviddelta/lingva-translate/main/README.md", regex_pattern=r"\|\s+\[(?P<domain>[\w\-\.\/\d]+)\]\(https:\/\/[\w\-\.\/\d]+\)(?:\s+\(Official\))?\s+\|\s+(?P<hosting>[^\|]+)\s+\|\s+(?P<ssl>[^\|]+)\s+\|"), )),
    InstancesGroupData(name="Whoogle", home_url="https://github.com/benbusby/whoogle-search#readme", relative_filepath_without_ext="search/whoogle",
                       instances=(RegexFromUrlInstance(relative_filepath_without_ext=Network.CLEARNET, url="https://raw.githubusercontent.com/benbusby/whoogle-search/main/README.md", regex_pattern=r"\|\s+\[https?:\/\/(?P<domain>[\w\-\.]+)\]\((?P<url>https?:\/\/[\w\-\.\/]+)\/?\)\s+\|\s+(?P<flagemoji>\W+)\s+(?P<country>\w+)\s+\|\s+(?P<language>\S+)\s+\|\s?(?P<cloudflare>(?:✅\s|\s))\|$"),
                                  RegexFromUrlInstance(relative_filepath_without_ext=Network.ONION, url="https://raw.githubusercontent.com/benbusby/whoogle-search/main/README.md", regex_pattern=r"\|?\s+\[https?:\/\/(?P<domain>[\w\-\.]+\.onion)\]\((?P<url>https?:\/\/[\w\-\.\/]+)\/?\)\s+\|\s+(?P<flagemoji>\W+)\s+(?P<country>\w+)\s+\|\s+(?P<language>\S+)\s+\|"),
                                  RegexFromUrlInstance(relative_filepath_without_ext=Network.I2P, url="https://raw.githubusercontent.com/benbusby/whoogle-search/main/README.md", regex_pattern=r"\|?\s+\[https?:\/\/(?P<domain>[\w\-\.]+\.i2p)\]\((?P<url>https?:\/\/[\w\-\.\/]+)\/?\)\s+\|\s+(?P<flagemoji>\W+)\s+(?P<country>\w+)\s+\|\s+(?P<language>\S+)\s+\|"))),
    InstancesGroupData(name="SearXNG", home_url="https://github.com/searxng/searxng#readme", relative_filepath_without_ext="search/searx",
                       instances=(JSONUsingCallableInstance(relative_filepath_without_ext=Network.CLEARNET, url="https://searx.space/data/instances.json", json_handle=lambda raw: tuple(map(get_domain_from_url, tuple(filter(lambda url: not any((".onion" in url, ".i2p" in url)), raw["instances"].keys()))))),
                                  JSONUsingCallableInstance(relative_filepath_without_ext=Network.ONION, url="https://searx.space/data/instances.json", json_handle=lambda raw: tuple(map(get_domain_from_url, tuple(filter(lambda url: ".onion" in url, raw["instances"].keys()))))),
                                  JSONUsingCallableInstance(relative_filepath_without_ext=Network.I2P, url="https://searx.space/data/instances.json", json_handle=lambda raw: tuple(map(get_domain_from_url, tuple(filter(lambda url: ".i2p" in url, raw["instances"].keys()))))))),
    InstancesGroupData(name="LibreX", home_url="https://github.com/hnhx/librex#readme", relative_filepath_without_ext="search/librex",
                       instances=(RegexFromUrlInstance(relative_filepath_without_ext=Network.CLEARNET, url="https://raw.githubusercontent.com/hnhx/librex/main/README.md", regex_group="clearnet", regex_pattern=r"\|\s+\[(?P<clearnet>[\w\-\.]+)\]\((?P<clearurl>https?:\/\/[\w\-\.\/]+)\)\s+\|\s+(?:❌|(?:\[✅\]\((?:http:\/\/)?(?P<onion>(?:\w|\.)+)\/?\)))\s+\|\s+(?:❌|(?:\[✅\]\((?:http:\/\/)?(?P<i2p>(?:\w|\.)+)\/?\)))\s+\|\s+(?P<flagemoji>\W+)\s+(?P<country>\w+)\s+(?:\(OFFICIAL\s+INSTANCE\)\s+)?\|"),
                                  RegexFromUrlInstance(relative_filepath_without_ext=Network.ONION, url="https://raw.githubusercontent.com/hnhx/librex/main/README.md", regex_group="onion", regex_pattern=r"\|\s+\[(?P<clearnet>[\w\-\.]+)\]\((?P<clearurl>https?:\/\/[\w\-\.\/]+)\)\s+\|\s+(?:❌|(?:\[✅\]\((?:http:\/\/)?(?P<onion>(?:\w|\.)+)\/?\)))\s+\|\s+(?:❌|(?:\[✅\]\((?:http:\/\/)?(?P<i2p>(?:\w|\.)+)\/?\)))\s+\|\s+(?P<flagemoji>\W+)\s+(?P<country>\w+)\s+(?:\(OFFICIAL\s+INSTANCE\)\s+)?\|"),
                                  RegexFromUrlInstance(relative_filepath_without_ext=Network.I2P, url="https://raw.githubusercontent.com/hnhx/librex/main/README.md", regex_group="i2p", regex_pattern=r"\|\s+\[(?P<clearnet>[\w\-\.]+)\]\((?P<clearurl>https?:\/\/[\w\-\.\/]+)\)\s+\|\s+(?:❌|(?:\[✅\]\((?:http:\/\/)?(?P<onion>(?:\w|\.)+)\/?\)))\s+\|\s+(?:❌|(?:\[✅\]\((?:http:\/\/)?(?P<i2p>(?:\w|\.)+)\/?\)))\s+\|\s+(?P<flagemoji>\W+)\s+(?P<country>\w+)\s+(?:\(OFFICIAL\s+INSTANCE\)\s+)?\|"))),
    InstancesGroupData(name="teddit", home_url="https://codeberg.org/teddit/teddit", relative_filepath_without_ext="reddit/teddit",
                       instances=(RegexFromUrlInstance(relative_filepath_without_ext=Network.CLEARNET, url="https://codeberg.org/teddit/teddit/raw/branch/main/README.md", regex_pattern=r"\|\s+(?:\[(?P<domain>[\w\-\.]+)\]\((?P<url>https?:\/\/[\w\-\.\/]+)\)\s+)?\|\s+(?:\[(?:http:\/\/)?[\w\-\.\/\d]+\]\(http:\/\/(?P<onion>[\w\-\.\/\d]+\.onion)\/?\)\s+)?\|\s+(?:\[(?:http:\/\/)?[\w\-\.\/\d]+\]\(http:\/\/(?P<i2p>[\w\-\.\/\d]+\.i2p)\/?\)\s+)?\|\s+(?P<notes>(?:[^\|])+)?\|"),
                                  RegexFromUrlInstance(relative_filepath_without_ext=Network.ONION, url="https://codeberg.org/teddit/teddit/raw/branch/main/README.md", regex_group="onion", regex_pattern=r"\|\s+(?:\[(?P<domain>[\w\-\.]+)\]\((?P<url>https?:\/\/[\w\-\.\/]+)\)\s+)?\|\s+(?:\[(?:http:\/\/)?[\w\-\.\/\d]+\]\(http:\/\/(?P<onion>[\w\-\.\/\d]+\.onion)\/?\)\s+)?\|\s+(?:\[(?:http:\/\/)?[\w\-\.\/\d]+\]\(http:\/\/(?P<i2p>[\w\-\.\/\d]+\.i2p)\/?\)\s+)?\|\s+(?P<notes>(?:[^\|])+)?\|"),
                                  RegexFromUrlInstance(relative_filepath_without_ext=Network.I2P, url="https://codeberg.org/teddit/teddit/raw/branch/main/README.md", regex_group="i2p", regex_pattern=r"\|\s+(?:\[(?P<domain>[\w\-\.]+)\]\((?P<url>https?:\/\/[\w\-\.\/]+)\)\s+)?\|\s+(?:\[(?:http:\/\/)?[\w\-\.\/\d]+\]\(http:\/\/(?P<onion>[\w\-\.\/\d]+\.onion)\/?\)\s+)?\|\s+(?:\[(?:http:\/\/)?[\w\-\.\/\d]+\]\(http:\/\/(?P<i2p>[\w\-\.\/\d]+\.i2p)\/?\)\s+)?\|\s+(?P<notes>(?:[^\|])+)?\|"))),
    InstancesGroupData(name="libreddit", home_url="https://github.com/libreddit/libreddit#readme", relative_filepath_without_ext="reddit/libreddit",
                       instances=(JSONUsingCallableInstance(relative_filepath_without_ext=Network.CLEARNET, url="https://raw.githubusercontent.com/libreddit/libreddit-instances/master/instances.json", json_handle=lambda raw: tuple(map(get_domain_from_url, tuple(filter(lambda url: url is not None, [x.get("url") for x in raw["instances"]]))))),
                                  JSONUsingCallableInstance(relative_filepath_without_ext=Network.ONION, url="https://raw.githubusercontent.com/libreddit/libreddit-instances/master/instances.json", json_handle=lambda raw: tuple(map(get_domain_from_url, tuple(filter(lambda url: url is not None, [x.get("onion") for x in raw["instances"]]))))))),
    InstancesGroupData(name="WikiLess", home_url="https://gitea.slowb.ro/ticoombs/Wikiless#wikiless", relative_filepath_without_ext="wikipedia/wikiless",
                       instances=(RegexCroppedFromUrlInstance(relative_filepath_without_ext=Network.CLEARNET, crop_from="## Instances", crop_to="## TODO", regex_group="domain", url="https://gitea.slowb.ro/ticoombs/Wikiless/raw/branch/main/README.md", regex_pattern=r"\(https?:\/\/(?:(?P<i2p>[\w\-\.\/\d]+\.i2p)|(?P<onion>[\w\-\.\/\d]+\.onion)|(?P<domain>[\w\-\.\/\d]+))\)"),
                                  RegexCroppedFromUrlInstance(relative_filepath_without_ext=Network.ONION, crop_from="## Instances", crop_to="## TODO", regex_group="onion", url="https://gitea.slowb.ro/ticoombs/Wikiless/raw/branch/main/README.md", regex_pattern=r"\(https?:\/\/(?:(?P<i2p>[\w\-\.\/\d]+\.i2p)|(?P<onion>[\w\-\.\/\d]+\.onion)|(?P<domain>[\w\-\.\/\d]+))\)"),
                                  RegexCroppedFromUrlInstance(relative_filepath_without_ext=Network.I2P, crop_from="## Instances", crop_to="## TODO", regex_group="i2p", url="https://gitea.slowb.ro/ticoombs/Wikiless/raw/branch/main/README.md", regex_pattern=r"\(https?:\/\/(?:(?P<i2p>[\w\-\.\/\d]+\.i2p)|(?P<onion>[\w\-\.\/\d]+\.onion)|(?P<domain>[\w\-\.\/\d]+))\)"))),
    InstancesGroupData(name="Piped", home_url="https://github.com/TeamPiped/Piped#readme", relative_filepath_without_ext="youtube/piped",
                       instances=(RegexFromUrlInstance(relative_filepath_without_ext=Network.CLEARNET, url="https://raw.githubusercontent.com/wiki/TeamPiped/Piped/Instances.md", domains_handle=lambda raw: tuple(map(lambda url: "piped."+url, raw)), regex_pattern=r"(?P<domain>[\w\-\.]+)(?:\s+\(Official\))?\s+\|\s+(?P<api>https?:\/\/[\w\-\.\/]+)\/?\s+\|(?P<locations>(?:[^\|])+)\|\s+(?:Yes|No)\s+\|", check_domain=True),  # TODO: FUCKING BULLSHIT. USE UPPTIME INFO WITH URLS
                                  GetDomainsFromHeadersInstance(relative_filepath_without_ext=Network.ONION, header=MirrorHeaders.ONION, main=BaseInstance(relative_filepath_without_ext=INST_FOLDER + "/youtube/piped/" + Network.CLEARNET)),
                                  GetDomainsFromHeadersInstance(relative_filepath_without_ext=Network.I2P, header=MirrorHeaders.I2P, main=BaseInstance(relative_filepath_without_ext=INST_FOLDER + "/youtube/piped/" + Network.CLEARNET)))),
    InstancesGroupData(name="Invidious", home_url="https://github.com/iv-org/invidious#readme", relative_filepath_without_ext="youtube/invidious",
                       instances=(JSONUsingCallableInstance(relative_filepath_without_ext=Network.CLEARNET, url="https://api.invidious.io/instances.json", json_handle=lambda raw: tuple(map(lambda inst: inst[0], tuple(filter(lambda inst: inst[1]["type"] == "https", raw))))),
                                  JSONUsingCallableInstance(relative_filepath_without_ext=Network.ONION, url="https://api.invidious.io/instances.json", json_handle=lambda raw: tuple(map(lambda inst: inst[0], tuple(filter(lambda inst: inst[1]["type"] == "onion", raw))))),
                                  JSONUsingCallableInstance(relative_filepath_without_ext=Network.I2P, url="https://api.invidious.io/instances.json", json_handle=lambda raw: tuple(map(lambda inst: inst[0], tuple(filter(lambda inst: inst[1]["type"] == "i2p", raw))))))),
    InstancesGroupData(name="HyperPipe", home_url="https://codeberg.org/Hyperpipe/Hyperpipe#hyperpipe", relative_filepath_without_ext="youtube/hyperpipe",
                       instances=(JSONUsingCallableInstance(relative_filepath_without_ext=Network.CLEARNET, url="https://raw.codeberg.page/Hyperpipe/pages/api/frontend.json", json_handle=lambda raw: tuple(filter(lambda url: not any((".onion" in url, ".i2p" in url)), tuple(map(lambda inst: re.match(r"https?\:\/\/([^\/\s]*)\/?", inst['url']).groups()[0], raw))))),
                                  JSONUsingCallableInstance(relative_filepath_without_ext=Network.ONION, url="https://raw.codeberg.page/Hyperpipe/pages/api/frontend.json", json_handle=lambda raw: tuple(filter(lambda url: ".onion" in url, tuple(map(lambda inst: re.match(r"https?\:\/\/([^\/\s]*)\/?", inst['url']).groups()[0], raw))))))),
    InstancesGroupData(name="Scribe", home_url="https://sr.ht/~edwardloveall/Scribe/", relative_filepath_without_ext="medium/scribe",
                       instances=(RegexCroppedFromUrlInstance(relative_filepath_without_ext=Network.CLEARNET, regex_group="domain", url="https://git.sr.ht/~edwardloveall/scribe/blob/HEAD/docs/instances.md", crop_from="# Instances", crop_to="## How do I get my instance on this list?", regex_pattern=r"[\<\(]https?:\/\/(?:(?P<onion>[\w\-\.\/\d]+\.onion)|(?P<i2p>[\w\-\.\/\d]+\.i2p)|(?P<domain>[\w\-\.\/\d]+))[\>\)]"),
                                  RegexCroppedFromUrlInstance(relative_filepath_without_ext=Network.ONION, regex_group="onion", url="https://git.sr.ht/~edwardloveall/scribe/blob/HEAD/docs/instances.md", crop_from="# Instances", crop_to="## How do I get my instance on this list?", regex_pattern=r"[\<\(]https?:\/\/(?:(?P<onion>[\w\-\.\/\d]+\.onion)|(?P<i2p>[\w\-\.\/\d]+\.i2p)|(?P<domain>[\w\-\.\/\d]+))[\>\)]"),
                                  RegexCroppedFromUrlInstance(relative_filepath_without_ext=Network.I2P, regex_group="i2p", url="https://git.sr.ht/~edwardloveall/scribe/blob/HEAD/docs/instances.md", crop_from="# Instances", crop_to="## How do I get my instance on this list?", regex_pattern=r"[\<\(]https?:\/\/(?:(?P<onion>[\w\-\.\/\d]+\.onion)|(?P<i2p>[\w\-\.\/\d]+\.i2p)|(?P<domain>[\w\-\.\/\d]+))[\>\)]"))),
    InstancesGroupData(name="Quetre", home_url="https://github.com/zyachel/quetre#readme", relative_filepath_without_ext="quora/quetre",
                       instances=(RegexCroppedFromUrlInstance(relative_filepath_without_ext=Network.CLEARNET, crop_from="1. Clearnet", crop_to="2. Onion", url="https://raw.githubusercontent.com/zyachel/quetre/main/README.md", regex_pattern=r"\|\s+\[(https?:\/\/)?(?P<domain>[\w\-\.\/\d]+)]\(https?:\/\/[\w\-\.\/\d]+\)\s+\|\s+(?P<region>[^\|]+)\|\s+(?P<provider>[^\|]+)\s+\|\s+(?P<note>[^\|]+)\s+\|"),
                                  RegexCroppedFromUrlInstance(relative_filepath_without_ext=Network.ONION, crop_from="2. Onion", crop_to="3. I2P", url="https://raw.githubusercontent.com/zyachel/quetre/main/README.md", regex_pattern=r"\|\s+\[(https?:\/\/)?(?P<domain>[\w\-\.\/\d]+)]\(https?:\/\/[\w\-\.\/\d]+\)\s+\|\s+(?P<region>[^\|]+)\|\s+(?P<provider>[^\|]+)\s+\|\s+(?P<note>[^\|]+)\s+\|"),
                                  RegexCroppedFromUrlInstance(relative_filepath_without_ext=Network.I2P, crop_from="3. I2P", crop_to="---", url="https://raw.githubusercontent.com/zyachel/quetre/main/README.md", regex_pattern=r"\|\s+\[(https?:\/\/)?(?P<domain>[\w\-\.\d]+)\/?\]\(https?:\/\/[\w\-\.\/\d]+?\)\s+\|\s+(?P<region>[^\|]+)\|\s+(?P<provider>[^\|]+)\s+\|\s+(?P<note>[^\|]+)\s+\|"))),
    InstancesGroupData(name="rimgo", home_url="https://codeberg.org/video-prize-ranch/rimgo#rimgo", relative_filepath_without_ext="imgur/rimgo",
                       instances=(RegexFromUrlInstance(relative_filepath_without_ext=Network.CLEARNET, url="https://codeberg.org/video-prize-ranch/rimgo/raw/branch/main/README.md", regex_pattern=r"\|\s+\[(?P<domain>[\w\-\.]+)\]\((?P<url>https?:\/\/[\w\-\.\/]+)\)+(?:\s+\(official\))?\s+\|\s+(?P<flagemoji>\W+)\s+(?P<country>\w+)\s+\|\s+(?P<provider>(?:[^\|])+)\s*\|\s+(?P<data>(?:[^\|])+)\s+\|(?P<notes>(?:[^\|])+)\|"),
                                  RegexCroppedFromUrlInstance(relative_filepath_without_ext=Network.ONION, url="https://codeberg.org/video-prize-ranch/rimgo/raw/branch/main/README.md", crop_from="### Tor", regex_pattern=r"\|\s+\[(?P<domain>[\w\-\.]+)\]\((?P<url>https?:\/\/[\w\-\.\/]+)\)+(?:\s+\(official\))?\s+\|\s+(?P<data>(?:[^\|])+)\s+\|(?P<notes>(?:[^\|])+)\|"))),
    InstancesGroupData(name="librarian", home_url="https://codeberg.org/librarian/librarian#librarian", relative_filepath_without_ext="odysee/librarian",
                       instances=(JSONUsingCallableInstance(relative_filepath_without_ext=Network.CLEARNET, url="https://codeberg.org/librarian/librarian/raw/branch/main/instances.json", json_handle=lambda raw: tuple(filter(lambda url: not any((".onion" in url, ".i2p" in url)), tuple(map(lambda inst: re.match(r"https?\:\/\/([^\/\s]*)\/?", inst['url']).groups()[0], raw["instances"]))))),
                                  JSONUsingCallableInstance(relative_filepath_without_ext=Network.ONION, url="https://codeberg.org/librarian/librarian/raw/branch/main/instances.json", json_handle=lambda raw: tuple(filter(lambda url: "onion" in url, tuple(map(lambda inst: re.match(r"https?\:\/\/([^\/\s]*)\/?", inst['url']).groups()[0], raw["instances"]))))))),
    InstancesGroupData(name="nitter", home_url="https://github.com/zedeus/nitter#readme", relative_filepath_without_ext="twitter/nitter",
                       instances=(RegexCroppedFromUrlInstance(relative_filepath_without_ext=Network.CLEARNET, url="https://raw.githubusercontent.com/wiki/zedeus/nitter/Instances.md", crop_to="### Tor", regex_pattern=(r"\|\s+\[(?P<domain>[\w\-\.]+)\]\((?P<clearurl>https?:\/\/[\w\-\.\/]+)\)(?P<anycast>\s+\(anycast\))?\s+\|\s+✅\s+\|\s+(?P<updated>\S+)\s+\|\s+(?P<flagemoji>\S+)\s+\|(?P<ssllabs>(?:[^\|])+)?\|", r"\|\s+\[(?P<domain>[\w\-\.]+)\]\((?P<clearurl>https?:\/\/[\w\-\.\/]+)\)\s+\|\s+(?P<flagemoji>\S+)\s+\|(?P<ssllabs>(?:[^\|])+)?\|")),
                                  RegexCroppedFromUrlInstance(relative_filepath_without_ext=Network.ONION, url="https://raw.githubusercontent.com/wiki/zedeus/nitter/Instances.md", crop_from="### Tor", crop_to=".i2p", regex_pattern=r"\|\s+\[(?P<domain>[\w\-\.]+)\/?\]\((?P<onionurl>https?:\/\/[\w\-\.\/]+)\)\s+\|\s+✅\s+\|", regex_group="domain"),
                                  RegexCroppedFromUrlInstance(relative_filepath_without_ext=Network.I2P, crop_from="### I2P", crop_to="### Lokinet", regex_pattern=r"-\s+\[(?P<domain>[\w\-\.]+)\]\((?P<i2purl>https?:\/\/[\w\-\.\/]+)\)", url="https://raw.githubusercontent.com/wiki/zedeus/nitter/Instances.md", regex_group="i2purl", domains_handle=lambda raw: tuple(map(get_domain_from_url, raw))),
                                  RegexCroppedFromUrlInstance(relative_filepath_without_ext=Network.LOKI, crop_from="### Lokinet", crop_to="## Discontinued", regex_pattern=r"-\s+\[(?P<domain>[\w\-\.]+)\]\((?P<lokiurl>https?:\/\/[\w\-\.\/]+)\)", url="https://raw.githubusercontent.com/wiki/zedeus/nitter/Instances.md", regex_group="lokiurl", domains_handle=lambda raw: tuple(map(get_domain_from_url, raw))))),
    InstancesGroupData(name="send", home_url="https://github.com/timvisee/send#readme", relative_filepath_without_ext="filedrop/send",
                       instances=(RegexCroppedFromUrlInstance(relative_filepath_without_ext=Network.CLEARNET, crop_from="## Instances", crop_to="---", url="https://raw.githubusercontent.com/timvisee/send-instances/master/README.md", regex_pattern=r"\-\s+https:\/\/(?P<domain>[\w\-\.]+)\s+\("), )),
    InstancesGroupData(name="breezewiki", home_url="https://gitdab.com/cadence/breezewiki", relative_filepath_without_ext="fandom/breezewiki",
                       instances=(JSONUsingCallableInstance(relative_filepath_without_ext=Network.CLEARNET, url="https://docs.breezewiki.com/files/instances.json", json_handle=lambda raw: tuple(map(lambda inst: get_domain_from_url(inst['instance']), raw))), )),
    InstancesGroupData(name="libmedium", home_url="https://github.com/realaravinth/libmedium", relative_filepath_without_ext="medium/libmedium",
                       instances=(RegexCroppedFromUrlInstance(relative_filepath_without_ext=Network.CLEARNET, url="https://raw.githubusercontent.com/realaravinth/libmedium/master/README.md", crop_from="## Instances", crop_to="##", regex_pattern=r"\|\s+https:\/\/(?P<domain>[\w\-\.]+)\/?\s+\|\s+(?P<country>(?:[^\|])+)\s+\|\s+(?P<provider>(?:[^\|])+)\s+\|\s+(?P<host>(?:[^\|])+)\|?"),
                                  RegexCroppedFromUrlInstance(relative_filepath_without_ext=Network.ONION, url="https://raw.githubusercontent.com/realaravinth/libmedium/master/README.md", crop_from="## Instances", crop_to="##", regex_pattern=r"\|\s+http:\/\/(?P<domain>[\w\-\.]+(?:\.onion))\/?\s+\|\s+(?P<country>(?:[^\|])+)\s+\|\s+(?P<provider>(?:[^\|])+)\s+\|\s+(?P<host>(?:[^\|])+)\|?"),
                                  RegexCroppedFromUrlInstance(relative_filepath_without_ext=Network.I2P, url="https://raw.githubusercontent.com/realaravinth/libmedium/master/README.md", crop_from="## Instances", crop_to="##", regex_pattern=r"\|\s+http:\/\/(?P<domain>[\w\-\.]+(?:\.i2p))\/?\s+\|\s+(?P<country>(?:[^\|])+)\s+\|\s+(?P<provider>(?:[^\|])+)\s+\|\s+(?P<host>(?:[^\|])+)\|?"))),
    InstancesGroupData(name="SimpleerTube", home_url="https://simple-web.org/projects/simpleertube.html", relative_filepath_without_ext="peertube/simpleertube",
                       instances=(JustFromUrlInstance(relative_filepath_without_ext=Network.CLEARNET, url="https://simple-web.org/instances/simpleertube"),
                                  JustFromUrlInstance(relative_filepath_without_ext=Network.ONION, url="https://simple-web.org/instances/simpleertube_onion"),
                                  JustFromUrlInstance(relative_filepath_without_ext=Network.I2P, url="https://simple-web.org/instances/simpleertube_i2p"))),
    InstancesGroupData(name="dumb", home_url="https://github.com/rramiachraf/dumb", relative_filepath_without_ext="genius/dumb",
                       instances=(RegexCroppedFromUrlInstance(relative_filepath_without_ext=Network.CLEARNET, url="https://raw.githubusercontent.com/rramiachraf/dumb/main/README.md", crop_from="## Public Instances", crop_to="##", regex_pattern=r"\|\s+\<https:\/\/(?P<domain>[\w\-\.]+)\>(?:\s+\(experimental\))?\s+\|\s+(?P<region>(?:[^\|])+)\s+\|\s+(?P<cdn>Yes|No)\s+\|\s+(?P<operator>(?:[^\|])+)\|?"),
                                  RegexCroppedFromUrlInstance(relative_filepath_without_ext=Network.ONION, url="https://raw.githubusercontent.com/rramiachraf/dumb/main/README.md", crop_from="## Public Instances", crop_to="##", regex_pattern=r"\|\s+\<http:\/\/(?P<domain>[\w\-\.]+\.onion)\>(?:\s+\(experimental\))?\s+\|\s+(?P<region>(?:[^\|])+)\s+\|\s+(?P<cdn>Yes|No)\s+\|\s+(?P<operator>(?:[^\|])+)\|?"),
                                  RegexCroppedFromUrlInstance(relative_filepath_without_ext=Network.I2P, url="https://raw.githubusercontent.com/rramiachraf/dumb/main/README.md", crop_from="## Public Instances", crop_to="##", regex_pattern=r"\|\s+\<http:\/\/(?P<domain>[\w\-\.]+\.i2p)\>(?:\s+\(experimental\))?\s+\|\s+(?P<region>(?:[^\|])+)\s+\|\s+(?P<cdn>Yes|No)\s+\|\s+(?P<operator>(?:[^\|])+)\|?"))),
    InstancesGroupData(name="biblioreads", home_url="https://github.com/nesaku/BiblioReads", relative_filepath_without_ext="goodreads/biblioreads",
                       instances=(RegexCroppedFromUrlInstance(relative_filepath_without_ext=Network.CLEARNET, url="https://raw.githubusercontent.com/nesaku/BiblioReads/main/README.md", crop_from="## Instances", crop_to="##", regex_pattern=r"\|\s+\[(?P<domain>[\w\-\.]+)\]\(https:\/\/[\w\-\.]+\)\s+\|"),
                                  RegexCroppedFromUrlInstance(relative_filepath_without_ext=Network.ONION, url="https://raw.githubusercontent.com/nesaku/BiblioReads/main/README.md", crop_from="## Instances", crop_to="##", regex_pattern=r"\|\s+\[(?P<domain>[\w\-\.]+\.onion)\]\(http:\/\/[\w\-\.]+\)\s+\|"),
                                  RegexCroppedFromUrlInstance(relative_filepath_without_ext=Network.I2P, url="https://raw.githubusercontent.com/nesaku/BiblioReads/main/README.md", crop_from="## Instances", crop_to="##", regex_pattern=r"\|\s+\[(?P<domain>[\w\-\.]+\.i2p)\]\(http:\/\/[\w\-\.]+\)\s+\|"))),
    InstancesGroupData(name="gothub", home_url="https://codeberg.org/gothub/gothub", relative_filepath_without_ext="github/gothub",
                       instances=(RegexFromUrlInstance(relative_filepath_without_ext=Network.CLEARNET, url="https://codeberg.org/gothub/gothub/wiki/raw/Instances.md", regex_pattern=r"\|\s+\[(?P<domain>[\w\-\.]+)\]\(https:\/\/[\w\-\.]+\)\s+\|"), )),
    InstancesGroupData(name="RYD-Proxy", home_url="https://github.com/TeamPiped/RYD-Proxy", relative_filepath_without_ext="ryd/rydproxy",
                       instances=(JustFromUrlInstance(relative_filepath_without_ext=Network.CLEARNET, url="https://raw.githubusercontent.com/NoPlagiarism/frontend-instances-custom/master/ryd/clearnet.txt"), )),
]


@logger.catch(reraise=True)
def main():
    for instance in INSTANCE_GROUPS:
        instance.from_instance().update()
        time.sleep(SLEEP_TIMEOUT_PER_GROUP)


@logger.catch(reraise=True)
async def async_main():
    tasks = list()
    for instance in INSTANCE_GROUPS:
        tasks.extend(instance.from_instance().get_coroutines())
    await asyncio.gather(*tasks)

def run():
    if ENABLE_ASYNC:
        asyncio.run(async_main())
    else:
        main()


if __name__ == "__main__":
    run()
