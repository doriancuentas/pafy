import sys
import re
import json

if sys.version_info[:2] >= (3, 0):
    # pylint: disable=E0611,F0401,I0011
    from urllib.parse import parse_qs, urlparse
    pyver = 3
else:
    from urlparse import parse_qs, urlparse
    pyver = 2

from . import g
from .pafy import new, get_categoryname, call_gdata, fetch_decode


def extract_playlist_id(playlist_url):
    # Normal playlists start with PL, Mixes start with RD + first video ID,
    # Liked videos start with LL, Uploads start with UU,
    # Favorites lists start with FL
    idregx = re.compile(r'((?:RD|PL|LL|UU|FL)[-_0-9a-zA-Z]+)$')

    playlist_id = None
    if idregx.match(playlist_url):
        playlist_id = playlist_url  # ID of video

    if '://' not in playlist_url:
        playlist_url = '//' + playlist_url
    parsedurl = urlparse(playlist_url)
    if parsedurl.netloc in ('youtube.com', 'www.youtube.com'):
        query = parse_qs(parsedurl.query)
        if 'list' in query and idregx.match(query['list'][0]):
            playlist_id = query['list'][0]

    return playlist_id


def get_playlist(playlist_url, basic=False, gdata=False,
                 size=False, callback=None):
    """ Return a dict containing Pafy objects from a YouTube Playlist.

    The returned Pafy objects are initialised using the arguments to
    get_playlist() in the manner documented for pafy.new()

    """

    playlist_id = extract_playlist_id(playlist_url)

    if not playlist_id:
        err = "Unrecognized playlist url: %s"
        raise ValueError(err % playlist_url)

    url = g.urls["playlist"] % playlist_id

    allinfo = fetch_decode(url)  # unicode
    allinfo = json.loads(allinfo)

    # playlist specific metadata
    playlist = dict(
        playlist_id=playlist_id,
        likes=allinfo.get('likes'),
        title=allinfo.get('title'),
        author=allinfo.get('author'),
        dislikes=allinfo.get('dislikes'),
        description=allinfo.get('description'),
        items=[]
    )

    # playlist items specific metadata
    for v in allinfo['video']:

        vid_data = dict(
            added=v.get('added'),
            is_cc=v.get('is_cc'),
            is_hd=v.get('is_hd'),
            likes=v.get('likes'),
            title=v.get('title'),
            views=v.get('views'),
            rating=v.get('rating'),
            author=v.get('author'),
            user_id=v.get('user_id'),
            privacy=v.get('privacy'),
            start=v.get('start', 0.0),
            dislikes=v.get('dislikes'),
            duration=v.get('duration'),
            comments=v.get('comments'),
            keywords=v.get('keywords'),
            thumbnail=v.get('thumbnail'),
            cc_license=v.get('cc_license'),
            category_id=v.get('category_id'),
            description=v.get('description'),
            encrypted_id=v.get('encrypted_id'),
            time_created=v.get('time_created'),
            time_updated=v.get('time_updated'),
            length_seconds=v.get('length_seconds'),
            end=v.get('end', v.get('length_seconds'))
        )

        try:
            pafy_obj = new(vid_data['encrypted_id'],
                           basic=basic,
                           gdata=gdata,
                           size=size,
                           callback=callback)

        except IOError as e:
            if callback:
                callback("%s: %s" % (v['title'], e.message))
            continue

        pafy_obj.populate_from_playlist(vid_data)
        playlist['items'].append(dict(pafy=pafy_obj,
                                      playlist_meta=vid_data))
        if callback:
            callback("Added video: %s" % v['title'])

    return playlist


def parseISO8591(duration):
    """ Parse ISO 8591 formated duration """
    regex = re.compile(r'PT((\d{1,3})H)?((\d{1,3})M)?((\d{1,2})S)?')
    if duration:
        duration = regex.findall(duration)
        if len(duration) > 0:
            _, hours, _, minutes, _, seconds = duration[0]
            duration = [seconds, minutes, hours]
            duration = [int(v) if len(v) > 0 else 0 for v in duration]
            duration = sum([60**p*v for p, v in enumerate(duration)])
        else:
            duration = 30
    else:
        duration = 30
    return duration


class Playlist(object):
    _items = None

    def __init__(self, playlist_url, basic, gdata, size, callback):
        playlist_id = extract_playlist_id(playlist_url)

        if not playlist_id:
            err = "Unrecognized playlist url: %s"
            raise ValueError(err % playlist_url)

        self.plid = playlist_id
        self._title = None
        self._author = None
        self._description = None
        self._len = None
        self._basic = basic
        self._gdata = gdata
        self._size = size
        self._callback = callback
        self._cached = 0
        self._pageToken = None

    @classmethod
    def from_dict(cls, pl, basic, gdata, size, callback):
        t = cls(pl['id'],  basic, gdata, size, callback)
        t._title = pl['title']
        t._author = pl['author']
        t._description = pl['description']
        t._len = pl['len']
        return t

    @classmethod
    def from_url(cls, url, basic, gdata, size, callback):
        t = cls(url,  basic, gdata, size, callback)
        t._fetch_basic()
        return t


    @property
    def title(self):
        if not self._title:
            self._fetch_basic()

        return self._title

    @property
    def author(self):
        if not self._author:
            self._fetch_basic()

        return self._author

    @property
    def description(self):
        if not self._description:
            self._fetch_basic()

        return self._description

    def __len__(self):
        if not self._len:
            self._fetch_basic()

        return self._len

    def __iter__(self):
        if self._items is not None:
            for i in self._items:
                yield i
            if self._pageToken == -1:
                return

        items = self._items
        if items is None:
            items = []

        # playlist items specific metadata
        query = {'part': 'snippet',
                 'maxResults': 50,
                 'playlistId': self.plid}

        while True:
            if self._pageToken:
                query['pageToken'] = self._pageToken
            playlistitems = call_gdata('playlistItems', query)

            query2 = {'part': 'contentDetails,snippet,statistics',
                      'maxResults': 50,
                      'id': ','.join(i['snippet']['resourceId']['videoId']
                                     for i in playlistitems['items'])}
            wdata = call_gdata('videos', query2)

            for v in wdata['items']:
                vid_data = dict_for_playlist(v)

                try:
                    pafy_obj = new(v['id'],
                                   basic=self._basic, gdata=self._gdata,
                                   size=self._size, callback=self._callback)

                except IOError as e:
                    if self._callback:
                        self._callback("%s: %s" % (v['title'], e.message))
                    continue

                pafy_obj.populate_from_playlist(vid_data)
                items.append(pafy_obj)
                if self._callback:
                    self._callback("Added video: %s" % vid_data['title'])
                yield pafy_obj

            if not playlistitems.get('nextPageToken'):
                self._pageToken = -1
                self._len = len(items)
                self._cached = self._len
                break

            query['pageToken'] = playlistitems['nextPageToken']
            self._pageToken = playlistitems['nextPageToken']

        self._items = items

    def __getitem__(self, index):
        if self._items is not None and index < self._cached:
            try:
                return self._items[index]
            except IndexError:
                pass

        if self._pageToken == -1:
            raise IndexError('index out of range')

        items = self._items
        if items is None:
            items = []
        i = index
        i -= self._cached

        query = {'part': 'snippet',
                 'maxResults': 50,
                 'playlistId': self.plid}

        while i >= 0:
            if self._pageToken:
                query['pageToken'] = self._pageToken
            playlistitems = call_gdata('playlistItems', query)

            query2 = {'part': 'contentDetails,snippet,statistics',
                      'maxResults': 50,
                      'id': ','.join(i['snippet']['resourceId']['videoId']
                                     for i in playlistitems['items'])}
            wdata = call_gdata('videos', query2)

            for v in wdata['items']:
                vid_data = dict_for_playlist(v)

                try:
                    pafy_obj = new(v['id'],
                                   basic=self._basic, gdata=self._gdata,
                                   size=self._size, callback=self._callback)

                except IOError as e:
                    if self._callback:
                        self._callback("%s: %s" % (v['title'], e.message))
                    continue

                pafy_obj.populate_from_playlist(vid_data)
                items.append(pafy_obj)
                i -= 1
                if self._callback:
                    self._callback("Added video: %s" % vid_data['title'])

            if not playlistitems.get('nextPageToken'):
                self._pageToken = -1
                self._len = len(items)
                break
            query['pageToken'] = playlistitems['nextPageToken']
            self._pageToken = playlistitems['nextPageToken']

        self._cached = len(items)
        self._items = items
        return self._items[index]

    def __setitem__(self, index, value):
        if self._items is not None:
            self._items[index] = value
            return

        items = self._items
        if items is None:
            items = []

        # playlist items specific metadata
        query = {'part': 'snippet',
                 'maxResults': 50,
                 'playlistId': self.plid}

        while True:
            if self._pageToken:
                query['pageToken'] = self._pageToken
            playlistitems = call_gdata('playlistItems', query)

            query2 = {'part': 'contentDetails,snippet,statistics',
                      'maxResults': 50,
                      'id': ','.join(i['snippet']['resourceId']['videoId']
                                     for i in playlistitems['items'])}
            wdata = call_gdata('videos', query2)

            for v in wdata['items']:
                vid_data = dict_for_playlist(v)

                try:
                    pafy_obj = new(v['id'],
                                   basic=self._basic, gdata=self._gdata,
                                   size=self._size, callback=self._callback)

                except IOError as e:
                    if self._callback:
                        self._callback("%s: %s" % (v['title'], e.message))
                    continue

                pafy_obj.populate_from_playlist(vid_data)
                items.append(pafy_obj)
                if self._callback:
                    self._callback("Added video: %s" % vid_data['title'])

            if not playlistitems.get('nextPageToken'):
                self._pageToken = -1
                self._len = len(items)
                self._cached = self._len
                break

            query['pageToken'] = playlistitems['nextPageToken']
            self._pageToken = playlistitems['nextPageToken']

        self._items = items
        self._items[index] = value

    def __repr__(self):
        if not self._title:
            self._fetch_basic()
        keys = "Type Title Author Description Length"
        keys = keys.split(" ")
        info = {"Type": "Playlist",
                "Title": self._title,
                "Author": self._author,
                "Description": self._description,
                "Length": self.__len__()}

        nfo = "\n".join(["%s: %s" % (k, info.get(k, "")) for k in keys])

        return nfo.encode("utf8", "replace") if pyver == 2 else nfo

    def _fetch_basic(self) :
        query = {'part': 'snippet, contentDetails',
                'id': self.plid}
        allinfo = call_gdata('playlists', query)

        pl = allinfo['items'][0]

        self._title = pl['snippet']['title']
        self._author = pl['snippet']['channelTitle']
        self._description = pl['snippet']['description']
        self._len = pl['contentDetails']['itemCount']


def get_playlist2(playlist_url, basic=False, gdata=False,
                  size=False, callback=None):
    """ Return a Playlist object from a YouTube Playlist.

    The returned Pafy objects are initialised using the arguments to
    get_playlist() in the manner documented for pafy.new()

    """

    return Playlist.from_url(playlist_url, basic, gdata, size, callback)


def dict_for_playlist(v):
    """Returns a dict which can be used to initialise Playlist Object."""

    stats = v.get('statistics', {})
    vid_data = dict(
        title=v['snippet']['title'],
        author=v['snippet']['channelTitle'],
        thumbnail=v['snippet'].get('thumbnails', {})
                              .get('default', {}).get('url'),
        description=v['snippet']['description'],
        length_seconds=parseISO8591(
                       v['contentDetails']['duration']),
        category=get_categoryname(v['snippet']['categoryId']),
        views=stats.get('viewCount', 0),
        likes=stats.get('likeCount', 0),
        dislikes=stats.get('dislikeCount', 0),
        comments=stats.get('commentCount', 0),
    )

    return vid_data
