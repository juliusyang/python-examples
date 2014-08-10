#!/usr/bin/python

# This script is written for python 2.7.*.

# It queries rottentomatoes for a list of currently
# released movies, extracts the IMDB id from the information,
# queries omdb if the IMDB id information is missing,
# and then counts the number of images in the imdb page
# for that movie.  It executes multiple HTTP queries in
# parallel for efficiency.

# I'm assuming grequests and gevent are installed.
# If not, the script could easily be converted to using
# Queue.

import cProfile
import grequests
import HTMLParser
import json
import math
import requests
import time

# RT developer account: julius5
# acct password is primary app password

class MyHTMLParser(HTMLParser.HTMLParser):
    # This class stores the number of img start
    # tags found on a web page in self.count.
    def __init__(self):
        HTMLParser.HTMLParser.__init__(self)
        self.count = 0

    def handle_starttag(self, tag, attrs):
        if tag == 'img':
            self.count += 1
        pass

    pass # End MyHTMLParser class


class Movie():
    # This instantiates an object with data from RT's api.
    def __init__(self):
        self.id = '' 
        self.title = ''
        self.year = 0
        self.mpaa_rating = ''
        self.runtime = 0
        self.critics_consensus = ''
        self.release_dates = {}
        self.ratings = {}
        self.synopsis = ''
        self.posters = {}
        self.abridged_cast = []
        self.alternate_ids = {} # Note this stores an imdb id ... how convenient.
        pass

    pass # End RTMovie class
      

def generateRtUrl(page, page_limit):
    # Obviously in production you would try to avoid storing
    # this key, in plaintext, in the app if at all possible.
    rtKey = 'aj3b8kvre9hury4ca98tz82w'

    # RT allows you to choose a page of movies (page) and to define the number of results
    # per page (page_limit).  page_limit maxes out at 50.
    rtUrl = 'http://api.rottentomatoes.com/api/public/v1.0/lists/movies/in_theaters.json?apikey=%s&page_limit=%s&page=%s&country=us' % (rtKey, page_limit, page)
    
    return rtUrl


def getTotalMovies():
    # Get one page with one result on it.
    # It will contain the total movies in current release.
    rtUrl = generateRtUrl(1,1)

    response = requests.get(rtUrl)

    if response.status_code != 200:
        raise Exception(str(response.status_code) + " " + response.reason)

    content = response.content
    data = json.loads(content)

    return data['total']


def instantiateMovieObjects(movies):
    movieObjects = []
    for movie in movies:
        m = Movie()
        for key in movie.keys():
            setattr(m, key, movie[key])
        pass
        movieObjects.append(m)
    pass

    return movieObjects
       

def generateOmdbUrl(title, year):
    url = 'http://www.omdbapi.com/?i=%s&t=%s' % (title, year)
    return url


def getImdbIdsFromOmdb(omdbMovies):
    urls = []
    imdbIds = []
    for omdbMovie in omdbMovies:
        title = omdbMovie.keys()[0]
        year = omdbMovie[title]

        url = generateOmdbUrl(title, year)
        urls.append(url)

    responses = getResponsesFromUrls(urls) 
    for response in responses:
        data = json.loads(response.content)
        imdbId = data['imdbID']
        imdbIds.append(imdbId)

    return imdbIds


def getImdbIds(movieObjects):
    imdbIds = []

    omdbMoviesToQuery = []
    for movieObject in movieObjects:

        alternate_ids = movieObject.alternate_ids

        if 'imdb' in alternate_ids:
            # RT doesn't prefix ids with tt, but OMDB does.
            imdbId = 'tt' + alternate_ids['imdb']
        else:
            # This entry on RT lacks the imdb id,
            # so let's get it from omdbapi.com.  Each entry in the
            # initial RT list is required to have an entry in the result.
            omdbMoviesToQuery.append({movieObject.title:movieObject.year})

        imdbIds.append(imdbId)

    imdbIdsFromOmdb = getImdbIdsFromOmdb(omdbMoviesToQuery)
    imdbIds = imdbIds + imdbIdsFromOmdb

    return imdbIds


def generateImdbUrl(imdbId):
    imdb_uri = 'http://www.imdb.com/title/%s' % imdbId

    return imdb_uri


def getResponsesFromUrls(urls):
    # Generate get requests for each url.
    reqs = (grequests.get(url) for url in urls)

    # Convert each request into a response.
    responses = grequests.map(reqs)

    return responses


def countImagesInHtml(html):
    # imdb pages aren't strictly ascii.  The html parser
    # will barf unless we feed it unicode.
    unicodeHtml = unicode(html, 'utf-8')
    htmlParser = MyHTMLParser()
    htmlParser.feed(unicodeHtml)
    count = htmlParser.count

    return count


def getImdbInfo(imdbIds):
    imdbInfo = []
    counts = []
    urls = [generateImdbUrl(imdbId) for imdbId in imdbIds]

    try:
        responses = getResponsesFromUrls(urls)
        htmlPages = [response.content for response in responses]
        counts = map(countImagesInHtml, htmlPages)
            
    except Exception, e:
        print str(e)

    for i in range(len(imdbIds)):
        # An ordered list of urls is constructed from an ordered list of imdbIDs,
        # the requests are constructed from an ordered list of urls,
        # the responses are constructed from the ordered list of
        # requests, and the image counts are extracted from the ordered list
        # of responses.  Therefore the values in each index of the arrays should
        # correspond.  Hey, dream big.
        url = urls[i]
        count = counts[i]
        anId = imdbIds[i]
        info = {}
        info['url'] = url
        info['count'] = count

        # Strip the leading 'tt' per the required final formatting
        info['imdb_id'] = anId[2:]

        imdbInfo.append(info)

    return imdbInfo


def getRtReleasedMoviesData(pagesToFetch, resultsPerPage):
    pageRange = range(1, pagesToFetch + 1) # range winds up [1,2,3] if pagesToFetch is 3
    urls = [generateRtUrl(page, resultsPerPage) for page in pageRange]

    movieData = []
    try:
        responses = getResponsesFromUrls(urls)
        for response in responses:
            data = json.loads(response.content)
            # data['movies'] is an array of up to 50 movies; we want
            # to concatenate the data from each array into the movieData
            # array
            movieData = movieData + data['movies']
    except Exception, e:
        print str(e)

    return movieData
        

def main():
    rtResultsPerPage = 50 # RT limits the number of results on one page to 50 max
    totalMovies = None
    try:
        totalMovies = getTotalMovies()
    except Exception, e:
        print str(e)
        return

    # How many pages do we need to fetch at n results per page?
    pagesToFetch = int(math.ceil(float(totalMovies/rtResultsPerPage)))

    movies = getRtReleasedMoviesData(pagesToFetch, rtResultsPerPage)

    # Converting the data into objects probably isn't
    # necessary.  But pre-parsing the data makes it
    # convenient to extract title and year for omdbapi.com.
    movieObjects = instantiateMovieObjects(movies)

    # Some testing code
    #m = Movie()
    #m.alternate_ids = {'imdb':'2015381'}
    #movieObjects = [m]

    imdbIds = getImdbIds(movieObjects)

    imdbInfo = getImdbInfo(imdbIds)

    print imdbInfo

    # This sleep tries to address a "won't fix" bug which throws an annoying error:
    # http://bugs.python.org/issue14623
    # See: http://stackoverflow.com/questions/7916749/multi-threading-exception-in-thread
    time.sleep(.1)

    return


# Trying to see where we can optimize, but it looks like mostly waiting for async calls
#cProfile.run('main()')

main()
