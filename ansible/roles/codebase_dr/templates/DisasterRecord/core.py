import atexit, xlrd, string, re, collections, operator
import sys, os, json, unicodedata, requests, Geohash
import time as tm
from tweepy.auth import OAuthHandler, API
from tweepy import StreamListener, streaming
from importlib import reload
from elasticsearch import Elasticsearch
from elasticsearch import helpers
from elasticsearch_dsl import Search, Q
from elasticsearch_dsl.connections import connections
import LNEx as lnex
from collections import defaultdict
import object_detection
from object_detection.ObjectDetector import ObjectDetector
OD = ObjectDetector()

import nltk
nltk.download('words')
nltk.download('stopwords')

from nltk.corpus import stopwords
from nltk.stem.wordnet import WordNetLemmatizer
from nltk import word_tokenize, pos_tag
from nltk.stem.porter import PorterStemmer
words = set(nltk.corpus.words.words())
stop = set(stopwords.words('english'))
exclude = set(string.punctuation)
lemma = WordNetLemmatizer()
token_dict = {}
stemmer = PorterStemmer()
printable = set(string.printable)

import traceback as tb
import urllib.request
from DRDB import DRDB

ES_SIZE = 1000


import threading

def log_it(data):
    with open('/var/log/DR.log', 'a') as fp:
        fp.write(str(data))
        fp.write('\n')

class DataProcess(object):

    def read(self, dataset, flood_flag, objects_flag, satellite_image, bb, shouldSleep=False, loopForever=False):
        
        start = 0
        end = 3
        es = Elasticsearch([{'host': '{{ photonip }}', 'port': {{ photonport }}}])
        geo_info = self.init_using_elasticindex(cache = False, augmentType = "HP", gaz_name = dataset, bb = bb, capital_word_shape = False)
        
        while 1:
          temp = es.search(index = dataset + '-file', body = {"size" : ES_SIZE, "query" : {"match_all" : {}}})['hits']['hits']
          temp_rec = [s['_source'] for s in temp]
          temp_id = list()

          for e in temp_rec:
            temp_id.append(e['record']['record-id'])

          end = max(temp_id)  #set maximum id number as the end of range.
          result = es.search(index = dataset + '-file', body = {"size" : ES_SIZE, "query" : {"bool" : {"must" : {"range" : {
                "record.record-id" : {
                    "gt" : start,
                    "lte" : end
                }
            }}}}})['hits']['hits']
          rec = [s['_source'] for s in result]

          if not loopForever and len(rec) == 0:
            log_it("FINISHED PROCESSING DATASET!")
            break

          for e in rec:
            text = e['record']['text']
            time = e['record']['time']
            imageurl = e['record']['imageurl']
            id = e['record']['id']
            all_geo_points = self.prepare_geo_points(dataset, text, time, id, imageurl, flood_flag, objects_flag, satellite_image, geo_info)

          if shouldSleep:
            tm.sleep(30)  #wait to read next batch
          start = end  #end becomes the start for the next iteration


    def clean(self, doc):
        
        stop_free = " ".join([i for i in doc.lower().split() if i not in stop])
        punc_free = ''.join(ch for ch in stop_free if ch not in exclude)
        normalized = " ".join(lemma.lemmatize(word) for word in punc_free.split())
        normalized = " ".join(stemmer.stem(word) for word in normalized.split())
        
        return normalized


    def preprocess_tweet(self, tweet):
        '''Preprocesses the tweet text and break the hashtags'''

        tweet = self.strip_non_ascii(tweet)
        tweet = str(tweet.lower())

        if tweet[:1] == "\n":
            tweet = tweet[1:len(tweet)]

        # remove retweet handler
        if tweet[:2] == "rt":
            try:
              colon_idx = tweet.index(": ")
              tweet = tweet[colon_idx + 2:]
            except BaseException:
              pass

        # remove url from tweet
        tweet = re.sub(r'\w+:\/{2}[\d\w-]+(\.[\d\w-]+)*(?:(?:\/[^\s/]*))*', 'URL', tweet)
        # remove non-ascii characters
        tweet = "".join([x for x in tweet if x in printable])
        # additional preprocessing
        tweet = tweet.replace("\n", " ").replace(" https", "").replace("http", "")
        # remove all mentions
        tweet = re.sub(r"@\w+", "@USER", tweet)
        # remove all mentions
        tweet = re.sub(r"#\w+", "#HASH", tweet)
        # padding punctuations
        tweet = re.sub('([,!?():])', r' \1 ', tweet)
        tweet = tweet.replace(". ", " . ").replace("-", " ")
        # shrink blank spaces in preprocessed tweet text to only one space
        tweet = re.sub('\s{2,}', ' ', tweet)
        tweet = " ".join(w for w in nltk.wordpunct_tokenize(tweet) if w.lower() in words or not w.isalpha())
        tweet = re.sub("^\d+\s|\s\d+\s|\s\d+$", " NUM ", tweet)
        tweet = tweet.replace('\n', '. ').replace('\t', ' ').replace(',', ' ').replace('"', ' ').replace("'", " ").replace(
            ";", " ").replace("\n", " ").replace("\r", " ")

        # remove trailing spaces
        tweet = tweet.strip()

        return tweet


    def strip_non_ascii(self,s):

        if isinstance(s, str):
            nfkd = unicodedata.normalize('NFKD', s)
            return str(nfkd.encode('ASCII', 'ignore').decode('ASCII'))
        else:
            return s


    def get_all_tweets_and_annotations(self, text, time, id, imageurl, flood_flag, objects_flag):

        lst=list()
        all_tweets_and_annotations=list()

        for img in imageurl:
            if flood_flag == "ON" and img != "null" and "http" in img:
                f = {'url': img}
                r = urllib.request.urlopen("http://127.0.0.1:30502/classify?{}".format(urllib.parse.urlencode(f)))
                r = r.readline().decode("utf-8")
                log_it("image inference made...")
                log_it(str(r))

                if str(r) == 'flood' and objects_flag == "ON":
                    obj = {}
                    url = img
                    water = True
                    img = {}
                    obj = OD.extract(url)
                    img = {"water": water, "objects": obj, "imageURL": url}
                    lst.append(img)

        text = self.strip_non_ascii(text)
        e = self.preprocess_tweet(text)

        try:
          text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore')
        except:
          pass

        all_tweets_and_annotations.append((text, id, time, lst, e))

        return all_tweets_and_annotations


    def init_using_elasticindex(self, cache, augmentType, gaz_name, bb, capital_word_shape):

        lnex.elasticindex(conn_string = '{{ photonip }}:{{ photonport }}', index_name = "photon")

        lnex.initialize(bb, augmentType = augmentType,
                            cache = cache,
                            dataset_name = gaz_name,
                            capital_word_shape = capital_word_shape,
                            isInit=True)
        a=0
        while a<1000:
            if lnex.is_cached(gaz_name):
                break
            else:
                tm.sleep(3)
            a+=1

        return  lnex.initialize(bb, augmentType = augmentType,
                                cache = cache,
                                dataset_name = gaz_name,
                                capital_word_shape = capital_word_shape,
                                isInit=False)



    def prepare_geo_points(self, dataset, text, time, id, imageurl, flood_flag, objects_flag, satellite_image, geo_info):

        log_it("STARTING PREPARE GEOPOINTS")

        os.environ['NO_PROXY'] = '127.0.0.1'
        all_geo_points = list()
        es = Elasticsearch([{'host' : '{{ photonip }}', 'port' : {{ photonport }}}])

        for tweet in self.get_all_tweets_and_annotations(text, time, id, imageurl, flood_flag, objects_flag):

            try:
                #classes = natural_language_classifier.classify('6876e8x557-nlc-635',tweet[0].decode("utf-8")).get_result()
                f = {'text': tweet[0].decode("utf-8")}
                r = urllib.request.urlopen("http://127.0.0.1:30501/classify?{}".format(urllib.parse.urlencode(f)))
                r = r.readline().decode("utf-8")
                log_it("RESULT:")
                log_it(str(r))

            except Exception as excp:
                var = tb.format_exc()
                log_it("**ERROR TRYING TO ACCESS CLASSIFIER...")
                log_it(str(var))
                #tm.sleep(30)
                continue

            #r = classes['top_class']

            if r == "shelter_matching":
                cl = "shelter_matching"
                i = '/static/shelter.png'
            elif r == "infrastructure_need":
                cl = "infrastructure_need"
                i = '/static/utility_infrastructure'
            elif r == "rescue_match":
                cl = "rescue_match"
                i = '/static/medical_need.png'
            else:
                cl = "not_related_or_irrelevant"
                i = ''

            for ln in lnex.extract(tweet[0].decode("utf-8")):

                if ln[0].lower() == dataset.lower():
                    continue

                ln_offsets = ln[1]
                geoinfo = [geo_info[x] for x in ln[3]["main"]]

                if len(geoinfo) == 0:
                    continue

                for geopoint in geoinfo:
                    lat = geopoint["geo_item"]["point"]["lat"]
                    lon = geopoint["geo_item"]["point"]["lon"]

                    try:
                        if satellite_image == "ON":

                            if str(fl) == 'True':
                                fld = True
                            else:
                                fld = False
                        else:
                            fld = False

                        es.index(index = dataset + '-tweetneeds', doc_type = 'doc', body = {"type" : "Feature", "geometry" : {"type" : "Point", "coordinates" : [lon, lat]}, "properties" : {"locationMention" : {"text" : ln[0], "offsets" : [ln_offsets[0],ln_offsets[1]]}, "tweetID" : tweet[1], "text" : tweet[0].decode("utf-8"), "createdAt" : tweet[2], "needClass" : cl, "flooded" : fld, "image" : tweet[3]}})
                        all_geo_points.append({"type" : "Feature", "geometry" : {"type" : "Point", "coordinates" : [lon, lat]}, "properties" : {"locationMention" : {"text" : ln[0], "offsets" : [ln_offsets[0],ln_offsets[1]]}, "tweetID" : tweet[1], "text" : tweet[0], "createdAt" : tweet[2], "needClass" : cl, "flooded" : fld, "image" : tweet[3]}})
                    except Exception as e:
                        log_it("**ERROR TRYING TO INDEX TWEETNEED...")
                        continue

        log_it("DONE PREPARE GEOPOINTS")

        return {"type" : "FeatureCollection", "features" : all_geo_points}


    def search_index(self, bb):
        '''Retrieves the location names from the elastic index using the given
        bounding box'''

        connections.create_connection(hosts = ["{{ photonip }}:{{ photonport }}"], timeout = 60)
        phrase_search = [Q({"bool": {
            "filter": {
              "geo_bounding_box": {
                "coordinate": {
                  "bottom_left": {
                    "lat" : bb[0],
                    "lon" : bb[1]
                  },
                  "top_right" : {
                    "lat" : bb[2],
                    "lon" : bb[3]
                  }
                }
              }
            },
            "must": {"match_all": {}}}})]
        #to search with a scroll
        e_search = Search(index = "photon").query(Q('bool', must = phrase_search))

        try:
            res = e_search.scan()
        except BaseException:
            raise

        return res


    def prepare_data_events(self, bb):

        log_it("BEGIN PREPARE DATA EVENTS WITH BB: {}".format(str(bb)))

        p_points = list()
        h = self.search_index(bb)
        x = 0
        es = Elasticsearch([{'host': '{{ photonip }}', 'port': {{ photonport }} }])

        actions=[]
        for match in h:

            try:
                if 'name' in match:

                    if 'default' in match["name"]:
                        x = 1
                        c = match["name"]['default']
                    elif 'en' in match["name"]:
                        x = 2
                        c = match["name"]['en']
                    elif 'fr' in match["name"]:
                        x = 3
                        c = match["name"]['fr']
                    elif 'alt' in match["name"]:
                        x = 4
                        c = match["name"]['alt']
                    elif 'old' in match["name"]:
                        x = 5
                        c = match["name"]['old']
                    else:
                        x = 6
                        c = match["name"]['loc']
                elif 'city' in match:
                    x = 7
                    c = match["city"]['default']
                else:
                    x = 8
                    c = match["country"]['default']

                lat = match["coordinate"]["lat"]
                lon = match["coordinate"]["lon"]
                k = match["osm_key"]
                v = match["osm_value"]

                if ((v == 'animal_shelter') or (v == 'bus_station') or (v == 'shelter') or (k == 'shop')):
                    cls = "shelter_matching"
                elif ((k == 'man_made' and v == 'pipeline') or (k == 'power' and v == 'line') or (
                        k == 'power' and v == 'plant') or (k == 'man_made' and v == 'communications_tower') or (
                        k == 'building' and v == 'transformer_tower') or (k == 'building' and v == 'service') or (
                        k == 'power' and v == 'minor_line') or (k == 'power' and v == 'substation') or (
                        k == 'craft' and v == 'electrician') or (k == 'craft' and v == 'scaffolder')):
                    cls = "infrastructure_need"
                elif ((v == 'fire_station') or (v == 'police') or (v == 'post_office') or (v == 'rescue_station') or (
                        v == 'hospital') or (v == 'ambulance_station') or (v == 'medical_supply') or (v == 'clinic') or (
                        v == 'doctors') or (v == 'social_facility') or (v == 'blood_donation') or (v == 'pharmacy') or (
                        v == 'nursing_home')):
                    cls = "rescue_match"
                else:
                    continue

                #fl = flooded(lat, lon)
                fl = False

                if str(fl) == 'True':
                    fl = True
                else:
                    log_it("prepare_data_events ES index action taken for {}\n".format(dataset))

                    fl = False
                    p_points.append({"type" : "Feature", "geometry" : {"type" : "Point", "coordinates" : [lon, lat]}, "properties" : {"name" : c, "key" : k, "value" : v, "needClass" : cls, "Flood" : fl}})
                    doc_body={"type" : "Feature", "geometry" : {"type" : "Point", "coordinates" : [lon, lat]}, "properties" : {"name" : c, "key" : k, "value" : v, "needClass" : cls, "Flood" : fl}}
                    action={
                        "_index":dataset+'-osm',
                        "_type":'doc',
                        "_source":doc_body}
                    actions.append(action)
            except:
                log_it("something went wrong with that event...")
        helpers.bulk(es, actions)
        actions=[]
        log_it("DONE PREPARE DATA EVENTS...")


def getTweets(hashtag, consumerkey, consumersecret, accesskey, accesssecret, dataset):

    # Twitter streams a Max of 57 tweets per second [Fact]
    #---------------------------------------------------------------------------
    print ("collecting tweets" )
    print ("====================================================================")
    reload(sys)
    #sys.setdefaultencoding('utf8')

    consumer_key = consumerkey
    consumer_secret = consumersecret
    access_key = accesskey
    access_secret = accesssecret

    auth = OAuthHandler(consumer_key, consumer_secret)
    auth.set_access_token(access_key, access_secret)
    api = API(auth)

    class CustomStreamListener(StreamListener):
        def on_data(self, data):

            item = json.loads(data)

            if 'text' in data:
                global REC_NUM
                REC_NUM = REC_NUM+1
                print ("==============================================================")
                print (REC_NUM)
                text=item['text']
                time=item['timestamp_ms']
                imageurl=[]
                try:
                  if item['extended_entites']['media']['type'] == "photo":
                      imageurl = item['extended_entites']['media']['media_url']
                except:
                  imageurl = []
                id = item['id']
                os.environ['NO_PROXY'] = '127.0.0.1'
                es = Elasticsearch([{'host' : '{{ photonip }}', 'port' : {{ photonport }}}])
                es.index(index = dataset + '-file', doc_type = 'doc', body = {"record" : {"text" :text, "time" : time, "imageurl" : imageurl, "id" : id, "record-id" : REC_NUM}})
            else:
                pass # Do nothing


        def on_error(self, status_code):
            
            print >> sys.stderr, 'Encountered error with status code:', status_code
            print ("sleeping for 16 minutes") # sleep for 16 minutes
            tm.sleep(960)

            return True # Don't kill the stream


        def on_timeout(self):

            print >> sys.stderr, 'Timeout...'
            return True # Don't kill the stream

    try:
        sapi = streaming.Stream(auth, CustomStreamListener())
        sapi.filter(track = hashtag, languages = ['en'])
    except:
        print ("tweepy error") #Don't do anythin
        raise


class ReadFromFile():
    def read_from_file(self, file_url):

        with open(file_url) as f:
            data = json.load(f)
        i = 0

        for e in data["_source"]:
            i+= 1
            text = e['record']['text']
            time = e['record']['time']
            imageurl = e['record']['imageurl']
            id = e['record']['id']
            es = Elasticsearch([{'host' : '{{ photonip }}', 'port' : {{ photonport }}}])
            es.index(index = dataset + '-file', doc_type = 'doc', body = {"record" : {"text" : text, "time" : time, "imageurl" : imageurl, "id" : id, "record-id" : i}})
    def readIRMAData(self):
        i=0
        
        data = urllib.request.urlopen("http://130.108.86.152/eventData/IRMASTest.txt")
        actions=[]
        es = Elasticsearch([{'host' : '{{ photonip }}', 'port' : {{ photonport }}}])
        log_it("  -->INSERTING IRMA DATA SET INTO ES")
        for line in data:
          try:
            line=line.decode()
            p1=line.find(",")
            user=line[0:p1]
            p2=line.find("\",\"")
            text=line[p1+2:p2]
            rest=line[p2+3:]
            p3=rest.find("\",\"")
            time_text=rest[:p3]
            imageurl=rest[p3+3:-3]
            fakeid=999999
            
            # example Thu Oct 05 12:17:37 EDT 2017
            pattern= '%a %b %d %H:%M:%S EDT %Y'
            time_epoch=int(tm.mktime(tm.strptime(time_text, pattern)))*1000
            

            action={
                "_index":dataset+'-file',
                "_type":'doc',
                "_source":{"record":{"text":text,"time":str(time_epoch),"imageurl":[imageurl],"id":fakeid,"record-id":i}}}
            actions.append(action)
          except:
            pass
          i+=1

        helpers.bulk(es, actions)
        actions=[]
        log_it("  -->DONE INSERTING IRMA DATA SET INTO ES [{} RECORDS]".format(i))
    def readDataset(self,file_url):
        i=0
        data = urllib.request.urlopen("{}".format(file_url))
        actions=[]
        es = Elasticsearch([{'host' : '{{ photonip }}', 'port' : {{ photonport }}}])
        log_it("  -->INSERTING DATA INTO ES")
        for line in data:
          try:
            line_decoded=line.decode("utf-8")
            o_doc=json.loads(str(line_decoded))
            a_doc={
                "_index":dataset+'-file',
                "_type":'doc',
                "_source":{"record":o_doc}
            }
            actions.append(a_doc)
          except:
            var = tb.format_exc()
            log_it("  -->ERROR ADDING DATA")
            log_it(str(var))
          i+=1

        helpers.bulk(es, actions)
        log_it("  -->DONE INSERTING DATA SET INTO ES [{} RECORDS]".format(i))
          


if __name__ == "__main__":

    global REC_NUM
    REC_NUM = 0

    log_it("STARTING DR BACKEND")
    keywords = sys.argv[1].split(" ")
    consumerkey = sys.argv[2]
    consumersecret = sys.argv[3]
    accesskey = sys.argv[4]
    accesssecret = sys.argv[5]
    dataset = sys.argv[6]
    flood_flag = sys.argv[7]
    objects_flag = sys.argv[8]
    boundingbox = sys.argv[10].split(" ")
    satellite_image = sys.argv[9]
    file_url = sys.argv[11]
    ptype = sys.argv[12]
    campaignName = sys.argv[13]
    mediaid = sys.argv[14]

    needed=True
    if ptype == "DATASET":
        pid=os.getpid()
        db=DRDB("/var/local/LNEx.db")
        db.update_drworker_pid(campaignName,mediaid,pid)
        db.destroy_connection()
        needed=False
        log_it("LOADING DATASET...")
        log_it("DATASET LOCATION: {}".format(file_url))
        f = ReadFromFile()
        f.readDataset(file_url)
        log_it("DONE LOADING DATASET")
        log_it("WAITING 5 SECONDS")
        tm.sleep(5)
        db=DRDB("/var/local/LNEx.db")
        c_info=db.get_campaign(campaignName)
        db.destroy_connection()
        bb_s=c_info[0][3].split(",")
        bb = [float(bb_s[i]) for i in range(len(bb_s))]
        log_it("STARTING DATA PROCESSING...")
        d = DataProcess()
        log_it("  -->BEGIN PREPARE")
        d.prepare_data_events(bb)
        log_it("  -->DONE PREPARE")
        d.read(dataset,flood_flag,objects_flag,satellite_image,bb,loopForever=False)
        log_it("  -->DONE READ")
        log_it("REACHED END OF PROCESSING")
        db=DRDB("/var/local/LNEx.db")
        db.update_media_object_status(mediaid,2)
        db.destroy_connection()

    elif ptype == "TWITTERSTREAM":
        needed=False
        #log_it("LOADING DATASET...")
        #log_it("DATASET LOCATION: {}".format(file_url))
        #f = ReadFromFile()
        #f.readDataset(file_url)
        #log_it("DONE LOADING DATASET")
        thread = threading.Thread(target=getTweets, args=(keywords,consumerkey,consumersecret,accesskey,accesssecret,dataset))
        thread.start()
        log_it("WAITING 5 SECONDS")
        tm.sleep(5)
        db=DRDB("/var/local/LNEx.db")
        c_info=db.get_campaign(campaignName)
        db.destroy_connection()
        bb_s=c_info[0][3].split(",")
        bb = [float(bb_s[i]) for i in range(len(bb_s))]
        log_it("STARTING DATA PROCESSING...")
        d = DataProcess()
        log_it("  -->BEGIN PREPARE")
        d.prepare_data_events(bb)
        log_it("  -->DONE PREPARE")
        d.read(dataset,flood_flag,objects_flag,satellite_image,bb,loopForever=True)
        log_it("  -->DONE READ")
        log_it("REACHED END OF PROCESSING")

    elif file_url == "None":
      log_it("STARTING TWEET STREAM")
      thread = threading.Thread(target=getTweets, args=(keywords,consumerkey,consumersecret,accesskey,accesssecret,dataset))
      thread.start()
    elif file_url == "IRMA":
      log_it("LOADING IRMA DATASET")
      f = ReadFromFile()
      f.readIRMAData()
      log_it("DONE LOADING IRMA DATASET")
    else:
      f = ReadFromFile()
      f.read_from_file(file_url)

    if needed:
        log_it("WAITING 5 SECONDS")
        tm.sleep(5)
        bb = [float(boundingbox[i]) for i in range(len(boundingbox))]
        log_it("STARTING DATA PROCESSING...")
        d = DataProcess()
        log_it("  -->BEGIN READ")
        d.read(dataset,flood_flag,objects_flag,satellite_image,bb)
        log_it("  -->DONE READ")
        log_it("  -->BEGIN PREPARE")
        d.prepare_data_events(bb)
        log_it("  -->DONE PREPARE")
        log_it("REACHED END OF PROCESSING")