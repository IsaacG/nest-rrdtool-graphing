#!/bin/python
"""
Create the RRD:

rrdtool create $HOME/.xdg/data/nest_thermostat.rrd \
--step '200' \
'DS:temperature:GAUGE:600:0:100' \
'DS:humidity:GAUGE:600:0:100' \
'DS:target:GAUGE:600:0:100' \
'DS:mode:GAUGE:600:0:10' \
'DS:state:ABSOLUTE:600:0:10' \
'DS:fan:GAUGE:600:0:1' \
\
'DS:ext_temperature:GAUGE:5400:0:100' \
'DS:ext_humidity:GAUGE:5400:0:100' \
\
'RRA:AVERAGE:0.5:1:2016' \
'RRA:AVERAGE:0.5:1:4032' \
'RRA:AVERAGE:0.5:6:1440' \
'RRA:AVERAGE:0.5:6:4416' \
'RRA:AVERAGE:0.5:12:4392' \
'RRA:AVERAGE:0.5:24:4380' \
'RRA:AVERAGE:0.5:48:4380'
"""

import enum
import nest
import os
import requests
import rrdtool
import secrets
import sys
import time


# Configs/secrets
ZIPCODE = secrets.ZIPCODE
NEST_CLIENT_ID = secrets.NEST_CLIENT_ID
NEST_CLIENT_SECRET = secrets.NEST_CLIENT_SECRET
WUNDERGROUND_API_KEY = secrets.WUNDERGROUND_API_KEY


class NestLogger(object):
  CLIENT_ID = NEST_CLIENT_ID
  CLIENT_SECRET = NEST_CLIENT_SECRET
  ACCESS_TOKEN_CACHE_FILE = '%s/.xdg/cache/nest.json' % os.environ['HOME']

  def __init__(self, rrd):
    self.Auth()
    self.rrd = rrd

  def Fetch(self):
    self.api = nest.Nest(
      client_id=self.CLIENT_ID, client_secret=self.CLIENT_SECRET,
      access_token_cache_file=self.ACCESS_TOKEN_CACHE_FILE) 

  def Auth(self):
    self.Fetch()
    # Nest data
    if self.api.authorization_required:
      raise Exception('Needs you to authorize!')
      print('Go to ' + napi.authorize_url + ' to authorize, then enter PIN below')
      pin = input("PIN: ")
      napi.request_token(pin)

  def Log(self):
    device = self.api.structures[0].thermostats[0]
    rrd_values = [
      'N',  # Timestamp=now
      device.temperature,
      device.humidity,
      device.target,
      HvacMode[device.mode.upper()].value,
      0 if device.hvac_state == 'off' else 1,
      1 if device.fan else 0,
      'U', 'U',  # Wunderground
    ]
    self.rrd.Update(rrd_values)

  def Update(self):
    self.Fetch()
    self.Log()


class RddTool(object):
  RRD = '%s/.xdg/data/nest_thermostat.rrd' % os.environ['HOME']
  GRAPH_INTERVAL = 5 * 60  # New graph every 5 min

  def __init__(self):
    self.last_graph = 0

  def Update(self, data):
    rrdtool.update(self.RRD, ':'.join([str(v) for v in data]))
    self.MaybeGraph()

  def MaybeGraph(self):
    if (time.time() - self.last_graph) < self.GRAPH_INTERVAL:
      return
    self.last_graph = time.time()
    os.system('%s/bin/nest_graph' % os.environ['HOME'])



class WUnderground(object):
  KEY = WUNDERGROUND_API_KEY
  MIN_WAIT = 5 * 60   # Wait at least 5 min between fetches
  FRESHNESS = 15 * 60 # Within 15m is still fresh
  ENDPOINT = 'http://api.wunderground.com/api/%s/conditions/q/%s.json'

  def __init__(self, rrd):
    self.last_fetch = 0
    self.rrd = rrd
  
  def Fetch(self):
    self.last_fetch = time.time()
    resp = requests.get(self.ENDPOINT % (self.KEY, ZIPCODE))
    self.data = resp.json()['current_observation']

  def Log(self):
    ext_temperature = self.data['temp_f']
    ext_humidity = self.data['relative_humidity'].rstrip('%')
    timestamp = self.data['local_epoch']

    rrd_values = [
      'N',  # It would be nice to use the timestamp but we can only add later values to RRD
      'U', 'U', 'U', 'U', 'U', 'U',  # Nest data
      ext_temperature,
      ext_humidity,
    ]
    self.rrd.Update(rrd_values)

  def MaybeUpdate(self):
    if (time.time() - self.last_fetch) < self.MIN_WAIT:
      return

    if self.last_fetch and (time.time() - int(self.data['local_epoch'])) < self.FRESHNESS:
      return

    self.Fetch()
    self.Log()

  def Update(self):
    self.MaybeUpdate()


class HvacMode(enum.Enum):
  OFF = 0
  ECO = 1
  HEAT = 2
  COOL = 3
  BOTH = 4


class Daemon(object):

  TICK_LEN = 90

  def __init__(self):
    self.rrd = RddTool()
    self.nest = NestLogger(self.rrd)
    self.wunderground = WUnderground(self.rrd)

  def Run(self):
    while True:
      self.RunOnce()
      time.sleep(self.TICK_LEN)
    
  def RunOnce(self):
    self.nest.Update()
    self.wunderground.Update()
  

def main():
  Daemon().Run()


if __name__ == '__main__':
  main()

