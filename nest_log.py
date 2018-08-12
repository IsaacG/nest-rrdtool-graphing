#!/bin/python
"""
Create the RRD:

rrdtool create $HOME/.xdg/data/nest_thermostat.rrd \
--step '200' \
'DS:temperature:GAUGE:600:0:100' \
'DS:humidity:GAUGE:600:0:100' \
'DS:target:GAUGE:600:0:100' \
'DS:mode:GAUGE:600:0:10' \
'DS:state:GAUGE:600:0:10' \
'DS:fan:GAUGE:600:0:1' \
'DS:away:GAUGE:600:0:1' \
\
'DS:ext_temperature:GAUGE:1500:0:100' \
'DS:ext_humidity:GAUGE:1500:0:100' \
\
'DS:solar_power:GAUGE:600:0:U' \
\
'RRA:AVERAGE:0.5:1:2016' \
'RRA:AVERAGE:0.5:1:4032' \
'RRA:AVERAGE:0.5:6:1440' \
'RRA:AVERAGE:0.5:6:4416' \
'RRA:AVERAGE:0.5:12:4392' \
'RRA:AVERAGE:0.5:24:4380' \
'RRA:AVERAGE:0.5:48:4380'
"""

import datetime
import enum
import nest
import os
import requests
import rrdtool
import sys
import time

import nest_secrets as secrets


class NestLogger(object):
  ACCESS_TOKEN_CACHE_FILE = '%s/.xdg/cache/nest.json' % os.environ['HOME']

  def __init__(self, client_id, secret):
    self.client_id = client_id
    self.secret = secret
    self._last = None

    self.Auth()

  def Fetch(self):
    self.api = nest.Nest(
      client_id=self.client_id, client_secret=self.secret,
      access_token_cache_file=self.ACCESS_TOKEN_CACHE_FILE)

  def Auth(self):
    self.Fetch()
    # Nest data
    try:
      authorization_required = self.api.authorization_required
    except requests.exceptions.ConnectionError:
      raise Exception('Connection error. Bail and retry later.')

    if authorization_required:
      raise Exception('Needs you to authorize!')
      print('Go to ' + self.api.authorize_url + ' to authorize, then enter PIN below')
      pin = input("PIN: ")
      self.api.request_token(pin)

  def GetData(self):
    self.Fetch()
    if self.api.structures and self.api.structures[0].thermostats:
      self._last = self.api.structures[0].thermostats[0]
    device = self._last
    return [
      device.temperature,
      device.humidity,
      device.target,
      HvacMode[device.mode.upper().replace('-', '')].value,
      0 if device.hvac_state == 'off' else 1,
      1 if device.fan else 0,
      1 if device.structure.away == 'away' else 0,
    ]


class RddTool(object):
  RRD = '%s/.xdg/data/nest_thermostat.rrd' % os.environ['HOME']
  GRAPH_INTERVAL = 5 * 60  # New graph every 5 min

  def __init__(self):
    self.last_graph = 0

  def Update(self, data):
    data.insert(0, 'N')
    data = ':'.join([str(v) for v in data])
    with open('/tmp/nest_rdd.log', 'a') as f:
      print('%s: Updating RRD with %s' % (datetime.datetime.now(), data), file=f)
    rrdtool.update(self.RRD, data)
    self.MaybeGraph()

  def MaybeGraph(self):
    if (time.time() - self.last_graph) < self.GRAPH_INTERVAL:
      return
    self.last_graph = time.time()
    os.system('%s/bin/nest_graph' % os.environ['HOME'])



class WUnderground(object):
  MIN_WAIT = 5 * 60   # Wait at least 5 min between fetches
  FRESHNESS = 10 * 60 # Within 15m is still fresh
  ENDPOINT = 'http://api.wunderground.com/api/%s/conditions/q/%s.json'

  def __init__(self, zipcode, key):
    self.last_fetch = 0
    self.zipcode = zipcode
    self.key = key

  def Fetch(self):
    self.last_fetch = time.time()
    resp = requests.get(self.ENDPOINT % (self.key, self.zipcode))
    if 'current_observation' in resp.json():
      self.data = resp.json()['current_observation']

  def GetData(self):
    fetch = True
    if (time.time() - self.last_fetch) < self.MIN_WAIT:
      fetch = False

    if self.last_fetch and (time.time() - int(self.data['local_epoch'])) < self.FRESHNESS:
      fetch = False

    if fetch:
      try:
        self.Fetch()
      except:
        pass

    ext_temperature = self.data['temp_f']
    ext_humidity = self.data['relative_humidity'].rstrip('%')
    return [ext_temperature, ext_humidity]


class Enphase(object):
  ENDPOINT = 'http://%s/api/v1/production'

  notes = """
   http get LOCAL_IP/production.json => "wNow":
   LOCAL_IP/backbone/application.js
   LOCAL_IP/inventory.json

   LOCAL_IP/api/v1/production

   https://thecomputerperson.wordpress.com/2016/08/03/enphase-envoy-s-data-scraping/
   """

  def __init__(self, local_ip):
    self.data = None
    self.local_ip = local_ip

  def Fetch(self):
    resp = requests.get(self.ENDPOINT % self.local_ip)
    self.data = resp.json()['wattsNow']

  def GetData(self):
    self.Fetch()

    return [self.data]


class HvacMode(enum.Enum):
  OFF = 0
  ECO = 1
  HEAT = 2
  COOL = 3
  HEATCOOL = 4


class Daemon(object):

  TICK_LEN = 90

  def __init__(self):
    self.rrd = RddTool()
    self.nest = NestLogger(secrets.NEST_CLIENT_ID, secrets.NEST_CLIENT_SECRET)
    self.wunderground = WUnderground(secrets.ZIPCODE, secrets.WUNDERGROUND_API_KEY)
    self.enphase = Enphase(secrets.ENPHASE_LOCAL_IP)

  def Run(self):
    while True:
      self.RunOnce()
      time.sleep(self.TICK_LEN)

  def RunOnce(self):
    data = (
      self.nest.GetData()
      + self.wunderground.GetData()
      + self.enphase.GetData()
    )
    self.rrd.Update(data)


def main():
  if 'once' in sys.argv:
    Daemon().RunOnce()
  else:
    Daemon().Run()


if __name__ == '__main__':
  main()

# vim:ts=2:sw=2:expandtab
