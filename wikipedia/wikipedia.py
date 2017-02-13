from __future__ import unicode_literals

import requests
import time
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from decimal import Decimal

from .exceptions import (
    PageError, DisambiguationError, RedirectError, HTTPTimeoutError,
    WikipediaException, ODD_ERROR_MESSAGE)
from .util import cache, stdout_encode, debug
from .version import get_version


API_URL = 'http://en.wikipedia.org/w/api.php'
RATE_LIMIT = False
RATE_LIMIT_MIN_WAIT = None
RATE_LIMIT_LAST_CALL = None
USER_AGENT = 'python-wikipedia-opensearch/{0} (https://github.com/stamkracht/wikipedia-opensearch/) BOT'.format(get_version())
SESSION = None


def set_lang(prefix):
    '''
    Change the language of the API being requested.
    Set `prefix` to one of the two letter prefixes found on the `list of all Wikipedias <http://meta.wikimedia.org/wiki/List_of_Wikipedias>`_.

    If the API endpoint is actually changed, function caches will be cleared.

    .. note:: Make sure you search for page titles in the language that you have set.
    '''
    global API_URL
    new_url = 'http://' + prefix.lower() + '.wikipedia.org/w/api.php'

    if new_url != API_URL:
        clear_cache()

    API_URL = new_url


def clear_cache():
    '''
    Clear the cached results as necessary
    '''
    for cached_func in (opensearch, search, suggest, summary, categorymembers, geosearch):
        cached_func.clear_cache()


def set_user_agent(user_agent_string):
    '''
    Set the User-Agent string to be used for all requests.

    Arguments:

    * user_agent_string - (string) a string specifying the User-Agent header
    '''
    global USER_AGENT

    USER_AGENT = user_agent_string
    reset_session()


def reset_session():
    '''
    Reset HTTP session
    '''
    global SESSION
    global USER_AGENT
    headers = {
        'User-Agent': USER_AGENT
    }
    SESSION = requests.Session()
    SESSION.headers.update(headers)


def set_rate_limiting(rate_limit, min_wait=timedelta(milliseconds=50)):
    '''
    Enable or disable rate limiting on requests to the Mediawiki servers.
    If rate limiting is not enabled, under some circumstances (depending on
    load on Wikipedia, the number of requests you and other `wikipedia` users
    are making, and other factors), Wikipedia may return an HTTP timeout error.

    Enabling rate limiting generally prevents that issue, but please note that
    HTTPTimeoutError still might be raised.

    Arguments:

    * rate_limit - (Boolean) whether to enable rate limiting or not

    Keyword arguments:

    * min_wait - if rate limiting is enabled, `min_wait` is a timedelta describing the minimum time to wait before requests.
                 Defaults to timedelta(milliseconds=50)
    '''
    global RATE_LIMIT
    global RATE_LIMIT_MIN_WAIT
    global RATE_LIMIT_LAST_CALL

    RATE_LIMIT = rate_limit
    if not rate_limit:
        RATE_LIMIT_MIN_WAIT = None
    else:
        RATE_LIMIT_MIN_WAIT = min_wait

    RATE_LIMIT_LAST_CALL = None


@cache
def search(query, results=10, suggestion=False):
    '''
    Do a Wikipedia search for `query`.

    Keyword arguments:

    * results - the maxmimum number of results returned
    * suggestion - if True, return results and suggestion (if any) in a tuple
    '''
    if query is None or query.strip() == '':
        raise ValueError("Query must be specified")
    search_params = {
        'list': 'search',
        'srprop': '',
        'srlimit': results,
        'limit': results,
        'srsearch': query
    }
    if suggestion:
        search_params['srinfo'] = 'suggestion'

    raw_results = _wiki_request(search_params)

    if isinstance(raw_results, dict) and 'error' in raw_results:
        if raw_results['error']['info'] in ('HTTP request timed out.', 'Pool queue is full'):
            raise HTTPTimeoutError(query)
        else:
            raise WikipediaException(raw_results['error']['info'])

    search_results = (d['title'] for d in raw_results['query']['search'])

    if suggestion:
        if raw_results['query'].get('searchinfo'):
            return list(search_results), raw_results['query']['searchinfo']['suggestion']
        else:
            return list(search_results), None

    return list(search_results)


@cache
def opensearch(query, limit=10, suggest=True, redirects='resolve'):
    '''
    Do a Wikipedia search for `query`.

    Keyword arguments:

    * limit - the maxmimum number of results returned
    * suggest - if True, return suggested pages as results
    * redirects - 'resolve' for target pages as results, 'return' for redirect pages as results
    '''
    if query is None or query.strip() == '':
        raise ValueError("Query must be specified")
    search_params = {
        'action': 'opensearch',
        'formatversion': 1,
        'search': query,
        'limit': limit,
        'suggest': int(suggest),
        'redirects': redirects
    }

    raw_results = _wiki_request(search_params)

    if isinstance(raw_results, dict) and 'error' in raw_results:
        if raw_results['error']['info'] in ('HTTP request timed out.', 'Pool queue is full'):
            raise HTTPTimeoutError(query)
        else:
            raise WikipediaException(raw_results['error']['info'])

    try:
        search_results = [
            OpensearchResult(raw_results[1][i], raw_results[2][i], raw_results[3][i])
            for i in range(len(raw_results[1]))]
    except Exception as err:
        raise WikipediaException(str(err))

    return search_results


class OpensearchResult(object):
    def __init__(self, title, summary, url):
        self.title = title
        self.summary = summary
        self.url = url

    def __repr__(self):
        return stdout_encode(u'<OpensearchResult \'{0}\'>'.format(self.title))

    def to_page(self):
        return WikipediaPage(title=self.title)


@cache
def categorymembers(category, results=10, subcategories=True):
    '''
    Do a Wikipedia search for pages, and optionally sub-categories, that belong to a `category`.

    Keyword arguments:

    * results - the maxmimum number of results returned
    * subcategories - if True, return pages and sub-categories (if any) in a tuple
    '''
    if category is None or category.strip() == '':
        raise ValueError("Category must be specified")

    search_params = {
        'list': 'categorymembers',
        'cmprop': 'ids|title|type',
        'cmtype': ('page|subcat' if subcategories else 'page'), # could also include files
        'cmlimit': results,
        'cmtitle': 'Category:' + category
    }

    raw_results = _wiki_request(search_params)

    if isinstance(raw_results, dict) and 'error' in raw_results:
        if raw_results['error']['info'] in ('HTTP request timed out.', 'Pool queue is full'):
            raise HTTPTimeoutError(search_params)
        else:
            raise WikipediaException(raw_results['error']['info'])

    pages = list()
    subcats = list()
    for d in raw_results['query']['categorymembers']:
        if d['type'] == 'page':
                pages.append(d['title'])
        elif d['type'] == 'subcat':
                tmp = d['title']
                if tmp.startswith('Category:'):
                        tmp = tmp[9:]
                subcats.append(tmp)
    if subcategories:
        return pages, subcats
    else:
        return pages


def categorytree(category, depth=5):
    '''
    Build a category tree for either a single category or a list of categories

    Keyword arguments:

    * depth - the maxmimum number of levels returned. < 0 for all levels

    .. note:: Set depth to 0 to get the full tree

    .. warning:: Very long running! Requires many calls to categorymembers; recommend setting rate limit before running.
    '''

    def __cat_tree_rec(cat, depth, tree, level):
        ''' recursive function to build out the tree '''
        tree[cat] = dict()
        tree[cat]['depth'] = level
        tree[cat]['sub-categories'] = dict()
        tree[cat]['links'] = list()
        tree[cat]['parent-categories'] = list()

        cat_page = page('Category:{0}'.format(cat))
        for p in cat_page.categories:
             tree[cat]['parent-categories'].append(p)

        cm = categorymembers(cat, 500, True)
        for link in cm[0]:
            tree[cat]['links'].append(link)

        if level >= depth > 0:
            for c in cm[1]:
                tree[cat]['sub-categories'][c] = None
        else:
            for c in cm[1]:
                __cat_tree_rec(c, depth, tree[cat]['sub-categories'], level + 1)
        return

    # make it simple to use both a list or a single category term
    if type(category) is not list:
        cats = [category]
    else:
        cats = category

    results = dict()
    for cat in cats:
        __cat_tree_rec(cat, depth, results, 0)
    return results


@cache
def geosearch(latitude, longitude, title=None, results=10, radius=1000):
    '''
    Do a wikipedia geo search for `latitude` and `longitude`
    using HTTP API described in http://www.mediawiki.org/wiki/Extension:GeoData

    Arguments:

    * latitude (float or decimal.Decimal)
    * longitude (float or decimal.Decimal)

    Keyword arguments:

    * title - The title of an article to search for
    * results - the maximum number of results returned
    * radius - Search radius in meters. The value must be between 10 and 10000
    '''
    if latitude is None or (type(latitude) != Decimal and latitude.strip() == ''):
        raise ValueError("Latitude must be specified")
    if longitude is None or (type(longitude) != Decimal and longitude.strip() == ''):
        raise ValueError("Longitude must be specified")

    search_params = {
        'list': 'geosearch',
        'gsradius': radius,
        'gscoord': '{0}|{1}'.format(latitude, longitude),
        'gslimit': results
    }
    if title:
        search_params['titles'] = title

    raw_results = _wiki_request(search_params)

    if isinstance(raw_results, dict) and 'error' in raw_results:
        if raw_results['error']['info'] in ('HTTP request timed out.', 'Pool queue is full'):
            raise HTTPTimeoutError('{0}|{1}'.format(latitude, longitude))
        else:
            raise WikipediaException(raw_results['error']['info'])

    search_pages = raw_results['query'].get('pages')
    if search_pages:
        search_results = (v['title'] for k, v in search_pages.items() if k != '-1')
    else:
        search_results = (d['title'] for d in raw_results['query']['geosearch'])

    return list(search_results)


@cache
def suggest(query):
    '''
    Get a Wikipedia search suggestion for `query`.
    Returns a string or None if no suggestion was found.
    '''
    if query is None or query.strip() == '':
        raise ValueError("Query must be specified")

    search_params = {
        'list': 'search',
        'srinfo': 'suggestion',
        'srprop': '',
    }
    search_params['srsearch'] = query

    raw_result = _wiki_request(search_params)

    if raw_result['query'].get('searchinfo'):
        return raw_result['query']['searchinfo']['suggestion']

    return None


def random(pages=1):
    '''
    Get a list of random Wikipedia article titles.

    .. note:: Random only gets articles from namespace 0, meaning no Category, User talk, or other meta-Wikipedia pages.

    Keyword arguments:

    * pages - the number of random pages returned (max of 10)
    '''
    #http://en.wikipedia.org/w/api.php?action=query&list=random&rnlimit=5000&format=jsonfm
    if pages is None or pages < 1:
        raise ValueError('Number of pages must be greater than 0')
    query_params = {
        'list': 'random',
        'rnnamespace': 0,
        'rnlimit': pages,
    }

    request = _wiki_request(query_params)
    titles = [page['title'] for page in request['query']['random']]

    if len(titles) == 1:
        return titles[0]

    return titles


@cache
def summary(title, sentences=0, chars=0, auto_suggest=True, redirect=True):
    '''
    Plain text summary of the page.

    .. note:: This is a convenience wrapper - auto_suggest and redirect are enabled by default

    Keyword arguments:

    * sentences - if set, return the first `sentences` sentences (can be no greater than 10).
    * chars - if set, return only the first `chars` characters (actual text returned may be slightly longer).
    * auto_suggest - let Wikipedia find a valid page title for the query
    * redirect - allow redirection without raising RedirectError
    '''

    if title is None or title.strip() == '':
        raise ValueError('Summary title must be specified.')

    # use auto_suggest and redirect to get the correct article
    # also, use page's error checking to raise DisambiguationError if necessary
    page_info = page(title, auto_suggest=auto_suggest, redirect=redirect)
    title = page_info.title
    pageid = page_info.pageid

    query_params = {
        'prop': 'extracts',
        'explaintext': '',
        'titles': title
    }

    if sentences:
        query_params['exsentences'] = sentences
    elif chars:
        query_params['exchars'] = chars
    else:
        query_params['exintro'] = ''

    request = _wiki_request(query_params)
    summary = request['query']['pages'][pageid]['extract']

    return summary


def page(title=None, pageid=None, auto_suggest=True, redirect=True, preload=False):
    '''
    Get a WikipediaPage object for the page with title `title` or the pageid
    `pageid` (mutually exclusive).

    Keyword arguments:

    * title - the title of the page to load
    * pageid - the numeric pageid of the page to load
    * auto_suggest - let Wikipedia find a valid page title for the query
    * redirect - allow redirection without raising RedirectError
    * preload - load content, summary, images, references, and links during initialization
    '''

    if title is not None and title.strip() != '':
        if auto_suggest:
            results, suggestion = search(title, results=1, suggestion=True)
            try:
                title = suggestion or results[0]
            except IndexError:
                # if there is no suggestion or search results, the page doesn't exist
                raise PageError(title)
        return WikipediaPage(title, redirect=redirect, preload=preload)
    elif pageid is not None:
        return WikipediaPage(pageid=pageid, preload=preload)
    else:
        raise ValueError("Either a title or a pageid must be specified")


class WikipediaPage(object):
    '''
    Contains data from a Wikipedia page.
    Uses property methods to filter data from the raw HTML.
    '''

    def __init__(self, title=None, pageid=None, redirect=True, preload=False, original_title=''):
        if title is not None:
            self.title = title
            self.original_title = original_title or title
        elif pageid is not None:
            self.pageid = pageid
        else:
            raise ValueError("Either a title or a pageid must be specified")

        self.__load(redirect=redirect, preload=preload)

        if preload:
            for prop in ('content', 'summary', 'images', 'references', 'links', 'sections', 'redirects', 'coordinates'):
                getattr(self, prop)

    def __repr__(self):
        return stdout_encode(u'<WikipediaPage \'{0}\'>'.format(self.title))

    def __eq__(self, other):
        try:
            return (
                self.pageid == other.pageid
                and self.title == other.title
                and self.url == other.url
            )
        except AttributeError:
            return False

    def __load(self, redirect=True, preload=False):
        '''
        Load basic information from Wikipedia.
        Confirm that page exists and is not a disambiguation/redirect.

        Does not need to be called manually, should be called automatically during __init__.
        '''
        query_params = {
            'prop': 'info|pageprops',
            'inprop': 'url',
            'ppprop': 'disambiguation',
            'redirects': '',
        }
        if not getattr(self, 'pageid', None):
            query_params['titles'] = self.title
        else:
            query_params['pageids'] = self.pageid

        request = _wiki_request(query_params)

        query = request['query']
        pageid = list(query['pages'].keys())[0]
        page = query['pages'][pageid]

        # missing is present if the page is missing
        if 'missing' in page:
            if hasattr(self, 'title'):
                raise PageError(self.title)
            else:
                raise PageError(pageid=self.pageid)

        # same thing for redirect, except it shows up in query instead of page for
        # whatever silly reason
        elif 'redirects' in query:
            if redirect:
                redirects = query['redirects'][0]

                if 'normalized' in query:
                    normalized = query['normalized'][0]
                    assert normalized['from'] == self.title, ODD_ERROR_MESSAGE

                    from_title = normalized['to']

                else:
                    if not getattr(self, 'title', None):
                        self.title = redirects['from']
                        delattr(self, 'pageid')
                    from_title = self.title

                assert redirects['from'] == from_title, ODD_ERROR_MESSAGE

                # change the title and reload the whole object
                self.__init__(redirects['to'], redirect=redirect, preload=preload)

            else:
                raise RedirectError(getattr(self, 'title', page['title']))

        # since we only asked for disambiguation in ppprop,
        # if a pageprop is returned,
        # then the page must be a disambiguation page
        elif 'pageprops' in page:
            query_params = {
                'prop': 'revisions',
                'rvprop': 'content',
                'rvparse': '',
                'rvlimit': 1
            }
            if hasattr(self, 'pageid'):
                query_params['pageids'] = self.pageid
            else:
                query_params['titles'] = self.title
            request = _wiki_request(query_params)
            html = request['query']['pages'][pageid]['revisions'][0]['*']

            lis = BeautifulSoup(html, 'html.parser').find_all('li')
            filtered_lis = [li for li in lis if not 'tocsection' in ''.join(li.get('class', list()))]
            may_refer_to = [li.a.get_text() for li in filtered_lis if li.a]
            disambiguation = list()
            for lis_item in filtered_lis:
                one_disambiguation = dict()
                item = lis_item.find_all("a")[0]
                one_disambiguation["title"] = item["title"]
                one_disambiguation["description"] = lis_item.text
                disambiguation.append(one_disambiguation)
            raise DisambiguationError(getattr(self, 'title', page['title']), may_refer_to, disambiguation)

        else:
            self.pageid = pageid
            self.title = page['title']
            self.url = page['fullurl']

    def __continued_query(self, query_params):
        '''
        Based on https://www.mediawiki.org/wiki/API:Query#Continuing_queries
        '''
        query_params.update(self.__title_query_param)

        last_continue = dict()
        prop = query_params.get('prop')

        while True:
            params = query_params.copy()
            params.update(last_continue)

            request = _wiki_request(params)

            if 'query' not in request:
                break

            pages = request['query']['pages']
            if 'generator' in query_params:
                for datum in pages.values():    # in python 3.3+: "yield from pages.values()"
                    yield datum
            else:
                for datum in pages[self.pageid].get(prop, list()):
                    yield datum

            if 'continue' not in request:
                break

            last_continue = request['continue']

    @property
    def __title_query_param(self):
        ''' util function to determine which parameter method to use '''
        if getattr(self, 'title', None) is not None:
            return {'titles': self.title}
        else:
            return {'pageids': self.pageid}

    def html(self):
        '''
        Get full page HTML.

        .. warning:: This can get pretty slow on long pages.
        '''
        if not getattr(self, '_html', False):
            query_params = {
                'prop': 'revisions',
                'rvprop': 'content',
                'rvlimit': 1,
                'rvparse': '',
                'titles': self.title
            }

            request = _wiki_request(query_params)
            self._html = request['query']['pages'][self.pageid]['revisions'][0]['*']

        return self._html

    @property
    def content(self):
        '''
        Plain text content of the page, excluding images, tables, and other data.
        '''
        if not getattr(self, '_content', False):
            query_params = {
                'prop': 'extracts|revisions',
                'explaintext': '',
                'rvprop': 'ids'
            }
            if getattr(self, 'title', None) is not None:
                 query_params['titles'] = self.title
            else:
                 query_params['pageids'] = self.pageid
            request = _wiki_request(query_params)
            self._content     = request['query']['pages'][self.pageid]['extract']
            self._revision_id = request['query']['pages'][self.pageid]['revisions'][0]['revid']
            self._parent_id   = request['query']['pages'][self.pageid]['revisions'][0]['parentid']

        return self._content

    @property
    def revision_id(self):
        '''
        Revision ID of the page.

        The revision ID is a number that uniquely identifies the current
        version of the page. It can be used to create the permalink or for
        other direct API calls. See `Help:Page history
        <http://en.wikipedia.org/wiki/Wikipedia:Revision>`_ for more
        information.
        '''
        if not getattr(self, '_revid', False):
            # fetch the content (side effect is loading the revid)
            self.content

        return self._revision_id

    @property
    def parent_id(self):
        '''
        Revision ID of the parent version of the current revision of this
        page. See ``revision_id`` for more information.
        '''
        if not getattr(self, '_parentid', False):
            # fetch the content (side effect is loading the parentid)
            self.content

        return self._parent_id

    @property
    def summary(self):
        '''
        Plain text summary of the page.
        '''
        if not getattr(self, '_summary', False):
            query_params = {
                'prop': 'extracts',
                'explaintext': '',
                'exintro': '',
            }
            if getattr(self, 'title', None) is not None:
                 query_params['titles'] = self.title
            else:
                 query_params['pageids'] = self.pageid

            request = _wiki_request(query_params)
            self._summary = request['query']['pages'][self.pageid]['extract']

        return self._summary

    @property
    def images(self):
        '''
        List of URLs of images on the page.
        '''
        if not getattr(self, '_images', False):
            self._images = list()
            for page in self.__continued_query({'generator': 'images', 'gimlimit': 'max', 'prop': 'imageinfo', 'iiprop': 'url'}):
                if 'imageinfo' in page:
                    self._images.append(page['imageinfo'][0]['url'])

        return self._images

    @property
    def coordinates(self):
        '''
        Tuple of Decimals in the form of (lat, lon) or None
        '''
        if not getattr(self, '_coordinates', False):
            query_params = {
                'prop': 'coordinates',
                'colimit': 'max',
                'titles': self.title,
            }

            request = _wiki_request(query_params)

            if 'query' in request and'coordinates' in  request['query']['pages'][self.pageid]:
                coordinates = request['query']['pages'][self.pageid]['coordinates']
                self._coordinates = (Decimal(coordinates[0]['lat']), Decimal(coordinates[0]['lon']))
            else:
                self._coordinates = None

        return self._coordinates

    @property
    def references(self):
        '''
        List of URLs of external links on a page.
        May include external links within page that aren't technically cited anywhere.
        '''
        if not getattr(self, '_references', False):
            self._references = list()
            for link in self.__continued_query({'prop': 'extlinks', 'ellimit': 'max'}):
                url = link['*'] if link['*'].startswith('http') else 'http:' + link['*']
                self._references.append(url)

        return self._references

    @property
    def links(self):
        '''
        List of titles of Wikipedia page links on a page.

        .. note:: Only includes articles from namespace 0, meaning no Category, User talk, or other meta-Wikipedia pages.
        '''
        if not getattr(self, '_links', False):
            self._links = list()
            for link in self.__continued_query({'prop': 'links', 'plnamespace': 0, 'pllimit': 'max'}):
                self._links.append(link['title'])

        return self._links

    @property
    def categories(self):
        '''
        List of non-hidden categories of a page.
        '''
        if not getattr(self, '_categories', False):
            self._categories = list()
            for link in self.__continued_query({'prop': 'categories', 'cllimit': 'max', 'clshow': '!hidden'}):
                if link['title'].startswith('Category:'):
                    self._categories.append(link['title'][9:])
                else:
                    self._categories.append(link['title'])

        return self._categories

    @property
    def redirects(self):
        '''
        List of all redirects to the page.
        '''
        if not getattr(self, '_redirects', False):
            self._redirects = list()
            for link in self.__continued_query({'prop': 'redirects','rdprop': 'title','rdlimit': '100'}):
                self._redirects.append(link['title'])

        return self._redirects

    @property
    def sections(self):
        '''
        List of section titles from the table of contents on the page.
        '''

        if not getattr(self, '_sections', False):
            query_params = {
                'action': 'parse',
                'prop': 'sections',
            }
            if not getattr(self, 'title', None):
                query_params['pageid'] = self.pageid
            else:
                query_params['page'] = self.title
            request = _wiki_request(query_params)
            self._sections = [section['line'] for section in request['parse']['sections']]

        return self._sections

    def section(self, section_title):
        '''
        Get the plain text content of a section from `self.sections`.
        Returns None if `section_title` isn't found, otherwise returns a whitespace stripped string.

        This is a convenience method that wraps self.content.

        .. warning:: Calling `section` on a section that has subheadings will NOT return
                     the full text of all of the subsections. It only gets the text between
                     `section_title` and the next subheading, which is often empty.
        '''

        section = u"== {0} ==".format(section_title)
        try:
            index = self.content.index(section) + len(section)
        except ValueError:
            return None

        try:
            next_index = self.content.index("==", index)
        except ValueError:
            next_index = len(self.content)

        return self.content[index:next_index].lstrip("=").strip()


@cache
def languages():
    '''
    List all the currently supported language prefixes (usually ISO language code).

    Can be inputted to `set_lang` to change the Mediawiki that `wikipedia` requests
    results from.

    Returns: dict of <prefix>: <local_lang_name> pairs. To get just a list of prefixes,
    use `wikipedia.languages().keys()`.
    '''
    response = _wiki_request({
        'meta': 'siteinfo',
        'siprop': 'languages'
    })

    languages = response['query']['languages']

    return {
        lang['code']: lang['*']
        for lang in languages
    }


def donate():
    '''
    Open up the Wikimedia donate page in your favorite browser.
    '''
    import webbrowser

    webbrowser.open('https://donate.wikimedia.org/w/index.php?title=Special:FundraiserLandingPage', new=2)


def _wiki_request(params):
    '''
    Make a request to the Wikipedia API using the given search parameters.
    Returns a parsed dict of the JSON response.
    '''
    global RATE_LIMIT_LAST_CALL
    global RATE_LIMIT
    global RATE_LIMIT_MIN_WAIT
    global SESSION

    params['format'] = 'json'
    if not 'action' in params:
        params['action'] = 'query'

    if RATE_LIMIT and RATE_LIMIT_LAST_CALL and RATE_LIMIT_LAST_CALL + RATE_LIMIT_MIN_WAIT > datetime.now():
        # it hasn't been long enough since the last API call
        # so wait until we're in the clear to make the request
        wait_time = (RATE_LIMIT_LAST_CALL + RATE_LIMIT_MIN_WAIT) - datetime.now()
        time.sleep(int(wait_time.total_seconds()))

    if SESSION is None:
        reset_session()

    r = SESSION.get(API_URL, params=params)

    if RATE_LIMIT:
        RATE_LIMIT_LAST_CALL = datetime.now()

    return r.json()
