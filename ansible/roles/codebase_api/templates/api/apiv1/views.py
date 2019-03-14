# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render
from django.http import HttpResponse
import json
import traceback as tb
from DRDB import DRDB
import redis
from subprocess import Popen, PIPE
from JobQueue import JobQueue
import os
import sys
import random
import time

r=redis.Redis(host='DR-redis')
jq=JobQueue("jobqueue",host='DR-redis')

def genRandKey():
  millis = int(round(time.time() * 1000))
  color = "%07x" % random.randint(0, 0xFFFFFFF)
  p1='{:x}'.format(millis)
  o=p1+str(color)
  return str(o)

def HKRset(key,val,db):
  _pre="LNEx_"
  _key=str(_pre)+str(key)
  r.set(_key, val)
  db.addRedisKey(_key)

def systemBusy():
  if r.exists("LNEx_ZONEINIT_ACTIVE"):
    initbusy = r.get("LNEx_ZONEINIT_ACTIVE")
    if initbusy == "0":
      return False
    else:
      return True


def LNExInit(request):
  try:
    #user = request.GET.get('user')
    key = request.GET.get('key')
    bb = request.GET.get('bb')
    if bb:
      bb = [ float(n) 
              for n in request
                .GET
                  .get('bb')
                    [1:-1]
                      .split(",")
           ]
      bb = [bb[1],bb[0],bb[3],bb[2]]
    zone = request.GET.get('zone')
    zone=zone.replace(" ","_")

    if zone and bb:
      msg = {"zone":str(zone),"bb":bb,"code":0}
      db=DRDB("/var/local/LNEx.db")
      verified = db.verify_key(str(key))
      if verified:
        if db.zn_count(str(key)):
          name_available = db.check_name(str(zone))
          if name_available:
            HKRset(str(zone)+"_ready",0,db)
            db.create_zone(str(zone), str(bb), str(key))
            if not systemBusy():
              r.set("LNEx_ZONEINIT_ACTIVE", 1)
              logfile = open('/var/log/LNEx.log', 'a')
              cmd = [
              '/root/workspace/LNEx/LNExEnv',
              'python',
              '/root/workspace/LNEx/initLoader.py',
              str(zone),
              "\"void\""]
              devnull = open(os.devnull, 'w')
              proc = Popen(
                  cmd,
                  shell=False,
                  stdin=devnull,
                  stdout=logfile,
                  stderr=logfile,
                  close_fds=True)
            else:
              msg={"notice": "system busy with another zone now","code":1}
              jq.put("init<|>{}".format(str(zone)))
          else:
            msg={"error": "zone \"{}\" in use".format(str(zone)),"code":2}
        else:
          msg={"error": "rate limit","code":3}
      else:
        msg={"error": "invalid key","code":4}
    else:
      msg={"error": "error in input","code":5}
  except:
    var = tb.format_exc()
    msg={"error": str(var),"code":9}

  c_t="application/json"
  c_p=json.dumps(msg,indent=2,sort_keys=True)
  try:
    db.destroy_connection()
  except:
    pass
  return HttpResponse(c_p, content_type=c_t)

def LNExDestroy(request):
  db=DRDB("/var/local/LNEx.db")
  try:
    zone = request.GET.get('zone')
    zone=zone.replace(" ","_")
    key = request.GET.get('key')
    verified = db.verify_key(str(key))
    if verified:
      if db.confirm_owner(zone,key):
        db.suspend_zone(zone)
        db.reduce_zoneCnt(key)
        msg={"notice":"{} has been destroyed".format(zone),"code":0}
      else:
        msg={"error":"invalid key","code":4}
    else:
      msg={"error":"invalid key","code":4}
  except:
    var = tb.format_exc()
    msg={"error": str(var),"code":9} 
  try:
    db.destroy_connection()
  except:
    pass
  c_t="application/json"
  c_p=json.dumps(msg,indent=2,sort_keys=True)
  return HttpResponse(c_p, content_type=c_t)

def LNExZoneReady(request):
  db=DRDB("/var/local/LNEx.db")
  try:
    key = request.GET.get('key')
    zone = request.GET.get('zone')
    zone=zone.replace(" ","_")
    verified = db.verify_key(str(key))
    if verified:
      if r.exists("LNEx_"+str(zone)+"_ready"):
        ready = r.get("LNEx_"+str(zone)+"_ready")
        if ready == "1":
          msg={"notice": "{} ready".format(zone),"code":0}
        else:
          msg={"notice":"zone not ready","code":7}
      else:
        msg={"error": "zone not found","code":6}
    else:
      msg={"error": "invalid key","code":4}
  except:
    var = tb.format_exc()
    msg={"error": str(var),"code":9}
  c_t="application/json"
  c_p=json.dumps(msg,indent=2,sort_keys=True)
  return HttpResponse(c_p,content_type=c_t)

def LNExPhotonID(request):
  db=DRDB("/var/local/LNEx.db")
  try:
    key = request.GET.get('key')
    osm_id = request.GET.get('osm_id')
    verified = db.verify_key(str(key))
    if verified:
      if db.go_count(str(key)):
        import requests
        ESURL="{{ photonip }}"
        ESPORT = "{{ photonport }}"
        r = requests.get("http://{}:{}/photon/_search?q=osm_id:{}".format(ESURL,ESPORT,osm_id))
        rjson = r.json()
        try:
          msg=rjson['hits']['hits'][0]['_source']
          msg['code']=0
        except:
          msg={'error':'osm_id {} not found'.format(osm_id),"code":6}
      else:
        msg={'error':'rate limit',"code":3}
    else:
      msg={'error':'invalid key',"code":4}
  except:
    var = tb.format_exc()
    msg={"error": str(var),"code":9}
  c_t="application/json"
  c_p=json.dumps(msg,indent=2,sort_keys=True)
  return HttpResponse(c_p,content_type=c_t)

"""
def LNExExtract(request):
  try:
    key = request.GET.get('key')
    zone = request.GET.get('zone')
    text = request.GET.get('text')
    meta = request.GET.get('meta', "False")
    if meta != "False" and meta != "True":
      meta = "False"
    if zone and text:
      t=text.encode('utf-8').strip()
      db=DRDB("/var/local/LNEx.db")
      verified = db.verify_key(str(key))
      if verified:
        if db.ex_count(str(key)):
          name_available = db.check_name(str(zone))
          if not name_available:
            if not systemBusy():
              keys=[
                  "LNEx_"+str(zone)+"_new_geo_locations",
                  "LNEx_"+str(zone)+"_geo_info",
                  "LNEx_"+str(zone)+"_extended_words3",
                  ]
              j=[r.exists(k) for k in keys]
              if r.exists("LNEx_"+str(zone)+"_ready") and all(j):
                ready = r.get("LNEx_"+str(zone)+"_ready")
              else:
                try:
                  r=db.get_zone(str(zone))
                  bb=r[0][2]
                  r.set("LNEx_ZONEINIT_ACTIVE", 1)
                  HKRset(str(zone)+"_ready",0,db)
                  logfile = open('/var/log/LNEx.log', 'a')
                  cmd = [
                  '/root/workspace/LNEx/LNExEnv',
                  'python',
                  '/root/workspace/LNEx/initLoader.py',
                  str(zone),
                  "\"void\""]
                  devnull = open(os.devnull, 'w')
                  proc = Popen(
                      cmd,
                      shell=False,
                      stdin=devnull,
                      stdout=logfile,
                      stderr=logfile,
                      close_fds=True)
                  msg={"error": "zone not ready"}
                  ready = "0"
                except:
                  ready = "0"
                  var = tb.format_exc()
                  msg={"error": str(var)}
              if ready == "1":
                resultKey=genRandKey()
                HKRset(str(resultKey)+"_resultReady",0,db)
                HKRset(str(resultKey)+"_queryText",str(text),db)
                r.set("LNEx_ZONEINIT_ACTIVE", 1)
                logfile = open('/var/log/LNEx.log', 'a')
                db.log_zone(str(zone))
                cmd = [
                '/root/workspace/LNEx/LNExEnv',
                'python',
                '/root/workspace/LNEx/query.py',
                str(zone),
                str(meta),
                str(resultKey),
                ]

                devnull = open(os.devnull, 'w')
                proc = Popen(
                    cmd,
                    shell=False,
                    stdin=devnull,
                    stdout=logfile,
                    stderr=logfile,
                    close_fds=True)
                msg = {"token": str(resultKey)}
              else:
                msg={"error": "zone not ready"}
            else:
              msg={"error": "system busy with another zone now"}
          else:
            msg={"error": "zone not found"}
        else:
          msg={"error": "rate limit"}
      else:
        msg={"error": "invalid key"}
    else:
      msg={"error": "invalid zone or text"}
  except:
    var = tb.format_exc()
    error["tb"] = str(var)
    msg = error

  c_t="application/json"
  c_p=json.dumps(msg,indent=2,sort_keys=True)
  try:
    db.destroy_connection()
  except:
    pass
  return HttpResponse(c_p, content_type=c_t)

"""

@csrf_exempt
def LNExBulkExtract(request):
  if request.method != 'POST':
    msg={"error": "must be a POST request"}
    c_t="application/json"
    c_p=json.dumps(msg,indent=2,sort_keys=True)
    return HttpResponse(c_p, content_type=c_t)
  try:
    key = request.GET.get('key')
    zone = request.GET.get('zone')
    zone=zone.replace(" ","_")
    text = request.body
    meta = request.GET.get('meta', "False")
    if meta != "False" and meta != "True":
      meta = "False"
    if zone and text:
      db=DRDB("/var/local/LNEx.db")
      verified = db.verify_key(str(key))
      if verified:
        name_available = db.check_name(str(zone))
        if not name_available:
          keys=[
              "LNEx_"+str(zone)+"_new_geo_locations",
              "LNEx_"+str(zone)+"_geo_info",
              "LNEx_"+str(zone)+"_extended_words3",
              ]
          j=[r.exists(k) for k in keys]
          if r.exists("LNEx_"+str(zone)+"_ready") and all(j):
            ready = r.get("LNEx_"+str(zone)+"_ready")
            if ready == "1":
              if db.ex_count(str(key)):
                resultKey=genRandKey()
                HKRset(str(resultKey)+"_resultReady",0,db)
                HKRset(str(resultKey)+"_queryText",str(text),db)
                db.log_zone(str(zone))
                msg={'token': str(resultKey),'code':0}
                if not systemBusy(): 
                  logfile = open('/var/log/LNEx.log', 'a')
                  r.set("LNEx_ZONEINIT_ACTIVE", 1)
                  cmd = [
                  '/root/workspace/LNEx/LNExEnv',
                  'python',
                  '/root/workspace/LNEx/queryBulk.py',
                  str(zone),
                  str(meta),
                  str(resultKey),
                  ]
                  devnull = open(os.devnull, 'w')
                  proc = Popen(
                      cmd,
                      shell=False,
                      stdin=devnull,
                      stdout=logfile,
                      stderr=logfile,
                      close_fds=True)
                else:
                  msg={"notice": "your request has been queued","code":1,"token":str(resultKey)}
                  jq.put("ext<|>{}<|>{}<|>{}".format(str(zone),str(meta),str(resultKey)))
              else:
                msg={"error": "rate limit","code":3}
            else:
              msg={"notice":"zone not ready","code":7}
          else:
            msg={"error": "zone not init","code":8}
        else:
          msg={"error":"zone not found","code":6}
      else:
        msg={"error":"invalid key","code":4}
    else:
      msg={"error": "invalid zone or text","code":5}
  except:
    var = tb.format_exc()
    msg={"error": str(var),"code":9}

  c_t="application/json"
  c_p=json.dumps(msg,indent=2,sort_keys=True)
  try:
    db.destroy_connection()
  except:
    pass
  return HttpResponse(c_p, content_type=c_t)

def LNExResults(request):
  try:
    key = request.GET.get('key')
    token = request.GET.get('token')
    if token:
      db=DRDB("/var/local/LNEx.db")
      verified = db.verify_key(str(key))
      if verified:
        if db.rs_count(str(key)):
          ready = r.get("LNEx_"+str(token)+"_resultReady")
          if ready and int(ready) > 0:
            results = r.get("LNEx_"+str(token)+"_results")
            msg=json.loads(results)
            msg['code']=0
            #r.set("LNEx"+str(token)+"_resultReady", 2)
            HKRset(str(token)+"_resultReady",2,db)
          else:
            msg={"notice": "results not ready","code":7}
        else:
          msg={"error": "rate limit","code":3}
    else:
      msg={"error": "invalid zone or text","code":5}
  except:
    var = tb.format_exc()
    msg={"error": str(var),"code":9}

  c_t="application/json"
  c_p=json.dumps(msg,indent=2,sort_keys=True)
  try:
    db.destroy_connection()
  except:
    pass
  return HttpResponse(c_p, content_type=c_t)


def LNExGeoInfo(request):
  try:
    key = request.GET.get('key')
    zone = request.GET.get('zone')
    zone=zone.replace(" ","_")
    #geoID = request.GET.get('geoID')
    geoIDs = request.GET.get('geoIDs')
    if geoIDs:
      geoIDs = [ str(n) 
              for n in request
                .GET
                  .get('geoIDs')
                    [1:-1]
                      .split(",")
           ]
      geoIDs=[x.strip() for x in geoIDs]
      geoIDs=[x.replace("'","") for x in geoIDs]
      geoID=",".join(geoIDs)
    if zone and geoID:
      db=DRDB("/var/local/LNEx.db")
      verified = db.verify_key(str(key))
      if verified:
        if db.go_count(str(key)):
          name_available = db.check_name(str(zone))
          if not name_available:
            resultKey=genRandKey()
            HKRset(str(resultKey)+"_resultReady",0,db)
            db.log_zone(str(zone))
            msg={'token': str(resultKey)}
            msg['code']=0
            if not systemBusy():
              try:
                logfile = open('/var/log/LNEx.log', 'a')
                r.set("LNEx_ZONEINIT_ACTIVE", 1)
                cmd = [
                '/root/workspace/LNEx/LNExEnv',
                'python',
                '/root/workspace/LNEx/geoInfo.py',
                str(zone),
                str(geoID),
                str(resultKey),]
                devnull = open(os.devnull, 'w')
                proc = Popen(
                    cmd,
                    shell=False,
                    stdin=devnull,
                    stdout=logfile,
                    stderr=logfile,
                    close_fds=True)
                #output=proc.stdout.readline()
                #msg=json.loads(output)
              except:
                var = tb.format_exc()
                msg={"error": str(var),"code":9}
            else:
              msg={"notice": "your request has been queued","code":1,"token":str(resultKey)}
              jq.put("geo<|>{}<|>{}<|>{}".format(str(zone),str(geoID),str(resultKey)))
          else:
            msg={"error": "zone not found","code":6}
        else:
          msg={"error": "rate limit","code":3}
      else:
        msg={"error": "invalid key","code":4}
    else:
      msg={"error": "invalid zone","code":5}
  except:
    var = tb.format_exc()
    msg={"error": str(var),"code":9}

  c_t="application/json"
  c_p=json.dumps(msg,indent=2,sort_keys=True)
  try:
    db.destroy_connection()
  except:
    pass
  return HttpResponse(c_p, content_type=c_t)

def handler404(request, *args, **argv):
    msg = {"error": "invalid url"}
    c_t="application/json"
    c_p=json.dumps(msg,indent=2,sort_keys=True)
    return HttpResponse(c_p, content_type=c_t)


def handler500(request, *args, **argv):
    msg = {"error": "invalid url"}
    c_t="application/json"
    c_p=json.dumps(msg,indent=2,sort_keys=True)
    return HttpResponse(c_p, content_type=c_t)