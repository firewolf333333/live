#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZakaLive · 色途成人直播頻道 —— TVBox Python 蜘蛛
===================================================================
站點：https://setu-adult-live.web.zaka.live

接口分析（2026-11-17 實測）
  · 站點是純靜態 SPA：index.html + style.css + app.js + data.json，沒有服務端 API。
  · 唯一的數據源是同源靜態檔 /data.json（28,845 B，JSON 陣列，130 條頻道）。
  · 無簽名、無 token、無 cookie、無 Referer/UA 校驗（空 header 直取 200）。
  · 分類、搜尋、分頁全部在 app.js 前端完成（對陣列做 filter + slice），
    服務端沒有對應接口，所以這裡一次取回 data.json，在本地做分類、搜尋、切片分頁。
  · poster 是相對路徑（img/tw01.jpg），要拼上站點域名。
  · 3 條走 cr.php?url= 反代，回 m3u8 正文但 content-type 是 application/json，
    content-type 不可信，只按 URL 判斷類型。

extend 寫法（站點域名換了或被牆時填）
  1) 空                    用內置站點
  2) 裸域名 / 多個域名      https://a.com   或   https://a.com,https://b.com
  3) 查詢串                domain=https://a.com&page_size=36&timeout=10&referer=
  4) JSON                  {"domain":"https://a.com","page_size":36,"timeout":10}

命令列
  python3 ZakaLive.py            真實聯網跑一遍全鏈路
  python3 ZakaLive.py --check    本地斷言自檢（不打網絡）
  python3 ZakaLive.py --offline  只用內置快照跑鏈路
"""

import json
import re
import sys
import time
import urllib.parse
import urllib.request

try:
    import requests
except Exception:                                   # 殼子裡沒裝 requests 時走 urllib
    requests = None

SITE_BASES = ["https://setu-adult-live.web.zaka.live"]
DATA_PATH = "/data.json"
DIAG_ID = "__zaka_diag__"
DIAG_NAME = "接口不通 · 點我看修法"
UA = ("Mozilla/5.0 (Linux; Android 14; V2354A) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36")
COOLDOWN = 90          # 失敗域名冷卻秒數
DEFAULT_CFG = {
    "domain": "",
    "page_size": 36,
    "timeout": 10,
    "ttl": 300,
    "ua": UA,
    "referer": "",
    "snapshot": True,
}

# 內置快照：2026-11-17 從 /data.json 原樣取回，僅在接口完全取不到時兜底，
# 讓列表至少不為空；快照裡的直播地址會隨時間失效，能聯網時一律以線上為準。
SNAPSHOT = r'''[{"id":"tw01","name":"驚艷台","sub":"成人電影","group":"台灣頻道","url":"http://15.204.105.50:25461/live/G2s9zK2n9m/xDtwVfWM8T/85.ts","res":"1920x1080","poster":"img/tw01.jpg","live":true,"views":0,"type":"ts"},{"id":"tw02","name":"驚艷台·備用","sub":"成人電影","group":"台灣頻道","url":"http://15.204.105.50:25461/live/G2s9zK2n9m/xDtwVfWM8T/87.ts","res":"1920x1080","poster":"img/tw02.jpg","live":true,"views":0,"type":"ts"},{"id":"tw03","name":"松視1台","sub":"成人頻道","group":"台灣頻道","url":"http://15.204.105.50:25461/live/G2s9zK2n9m/xDtwVfWM8T/88.ts","res":"1920x1080","poster":"img/tw03.jpg","live":true,"views":0,"type":"ts"},{"id":"tw04","name":"松視2台","sub":"成人頻道","group":"台灣頻道","url":"http://15.204.105.50:25461/live/G2s9zK2n9m/xDtwVfWM8T/89.ts","res":"1920x1080","poster":"img/tw04.jpg","live":true,"views":0,"type":"ts"},{"id":"tw05","name":"松視3台","sub":"成人頻道","group":"台灣頻道","url":"http://15.204.105.50:25461/live/G2s9zK2n9m/xDtwVfWM8T/90.ts","res":"1920x1080","poster":"img/tw05.jpg","live":true,"views":0,"type":"ts"},{"id":"tw06","name":"香蕉台","sub":"成人頻道","group":"台灣頻道","url":"http://15.204.105.50:25461/live/G2s9zK2n9m/xDtwVfWM8T/117.ts","res":"1920x1080","poster":"img/tw06.jpg","live":true,"views":0,"type":"ts"},{"id":"tw07","name":"潘朵拉粉紅","sub":"成人電影","group":"台灣頻道","url":"http://15.204.105.50:25461/live/G2s9zK2n9m/xDtwVfWM8T/86.ts","res":"1920x1080","poster":"img/tw07.jpg","live":true,"views":0,"type":"ts","hevc":true},{"id":"tw08","name":"潘朵拉完美","sub":"成人電影","group":"台灣頻道","url":"http://srteamhls.gotvsports.com:41111/04v9iycrpkoelo1b/index.m3u8","res":"1920x1080","poster":"img/tw08.jpg","live":true,"views":0,"type":"hls"},{"id":"tw09","name":"樂活頻道","sub":"綜合影視","group":"台灣頻道","url":"http://srteamhls.gotvsports.com:41111/i0a2mditbdzv0h4e/index.m3u8","res":"1920x1080","poster":"img/tw09.jpg","live":true,"views":0,"type":"hls"},{"id":"tw10","name":"彩虹電影","sub":"成人電影","group":"台灣頻道","url":"http://srteamhls.gotvsports.com:41111/w8chslnwkcidbh3r/index.m3u8","res":"1920x1080","poster":"img/tw10.jpg","live":true,"views":0,"type":"hls"},{"id":"tw11","name":"彩虹R","sub":"成人電影","group":"台灣頻道","url":"http://srteamhls.gotvsports.com:41111/f35jovi7msk6dd4p/index.m3u8","res":"1920x1080","poster":"img/tw11.jpg","live":true,"views":0,"type":"hls"},{"id":"tw12","name":"彩虹E","sub":"成人電影","group":"台灣頻道","url":"http://srteamhls.gotvsports.com:41111/gk1lhs34k93w0egd/index.m3u8","res":"1920x1080","poster":"img/tw12.jpg","live":true,"views":0,"type":"hls"},{"id":"tw13","name":"極限電影台","sub":"成人電影","group":"台灣頻道","url":"http://srteamhls.gotvsports.com:41111/s0doso0ydxe3yk2s/index.m3u8","res":"1920x1080","poster":"img/tw13.jpg","live":true,"views":0,"type":"hls"},{"id":"tw14","name":"HOT","sub":"成人頻道","group":"台灣頻道","url":"http://srteamhls.gotvsports.com:41111/krxh0hci5hfbsq7o/index.m3u8","res":"1920x1080","poster":"img/tw14.jpg","live":true,"views":0,"type":"hls"},{"id":"tw15","name":"Happy","sub":"成人頻道","group":"台灣頻道","url":"http://srteamhls.gotvsports.com:41111/ynmiv1i5as4k1oue/index.m3u8","res":"1920x1080","poster":"img/tw15.jpg","live":true,"views":0,"type":"hls"},{"id":"tw16","name":"FLIXKO","sub":"成人電影","group":"台灣頻道","url":"http://x315601.serv00.net/cr.php?url=http://lc.aacalive.com:26789/i/ghjnvq5o/8jainsbq/index.m3u8","res":"1920x1080","poster":"img/tw16.jpg","live":true,"views":0,"type":"hls","hevc":true},{"id":"tw17","name":"IPPA","sub":"成人電影","group":"台灣頻道","url":"http://x315601.serv00.net/cr.php?url=http://lc.aacalive.com:26789/i/ghjnvq5o/v19a2133/index.m3u8","res":"1280x720","poster":"img/tw17.jpg","live":true,"views":0,"type":"hls","hevc":true},{"id":"tw18","name":"麻豆傳媒映畫","sub":"成人電影","group":"台灣頻道","url":"http://x315601.serv00.net/cr.php?url=http://lc.aacalive.com:26789/i/ghjnvq5o/asdm3134/index.m3u8","res":"1920x1080","poster":"img/tw18.jpg","live":true,"views":0,"type":"hls","hevc":true},{"id":"tv01","name":"肛交","sub":"歐美成人台","group":"歐美","url":"https://live.adultiptv.net/anal.m3u8","res":"1280x720","poster":"img/tv01.jpg","live":true,"views":0},{"id":"tv02","name":"亞洲","sub":"歐美成人台","group":"歐美","url":"https://live.adultiptv.net/asian.m3u8","res":"1280x720","poster":"img/tv02.jpg","live":true,"views":0},{"id":"tv03","name":"巨臀","sub":"歐美成人台","group":"歐美","url":"https://live.adultiptv.net/bigass.m3u8","res":"1280x720","poster":"img/tv03.jpg","live":true,"views":0},{"id":"tv04","name":"巨屌","sub":"歐美成人台","group":"歐美","url":"https://live.adultiptv.net/bigdick.m3u8","res":"1280x720","poster":"img/tv04.jpg","live":true,"views":0},{"id":"tv05","name":"巨乳","sub":"歐美成人台","group":"歐美","url":"https://live.adultiptv.net/bigtits.m3u8","res":"1280x720","poster":"img/tv05.jpg","live":true,"views":0},{"id":"tv06","name":"金髮","sub":"歐美成人台","group":"歐美","url":"https://live.adultiptv.net/blonde.m3u8","res":"1280x720","poster":"img/tv06.jpg","live":true,"views":0},{"id":"tv07","name":"口交","sub":"歐美成人台","group":"歐美","url":"https://live.adultiptv.net/blowjob.m3u8","res":"1280x720","poster":"img/tv07.jpg","live":true,"views":0},{"id":"tv08","name":"黑髮","sub":"歐美成人台","group":"歐美","url":"https://live.adultiptv.net/brunette.m3u8","res":"1280x720","poster":"img/tv08.jpg","live":true,"views":0},{"id":"tv09","name":"精選合集","sub":"歐美成人台","group":"歐美","url":"https://live.adultiptv.net/compilation.m3u8","res":"1280x720","poster":"img/tv09.jpg","live":true,"views":0},{"id":"tv10","name":"綠帽","sub":"歐美成人台","group":"歐美","url":"https://live.adultiptv.net/cuckold.m3u8","res":"1280x720","poster":"img/tv10.jpg","live":true,"views":0},{"id":"tv11","name":"戀物","sub":"歐美成人台","group":"歐美","url":"https://live.adultiptv.net/fetish.m3u8","res":"1280x720","poster":"img/tv11.jpg","live":true,"views":0},{"id":"tv12","name":"群交","sub":"歐美成人台","group":"歐美","url":"https://live.adultiptv.net/gangbang.m3u8","res":"1280x720","poster":"img/tv12.jpg","live":true,"views":0},{"id":"tv13","name":"男同","sub":"歐美成人台","group":"歐美","url":"https://live.adultiptv.net/gay.m3u8","res":"1280x720","poster":"img/tv13.jpg","live":true,"views":0},{"id":"tv14","name":"硬核","sub":"歐美成人台","group":"歐美","url":"https://live.adultiptv.net/hardcore.m3u8","res":"1280x720","poster":"img/tv14.jpg","live":true,"views":0},{"id":"tv15","name":"跨種族","sub":"歐美成人台","group":"歐美","url":"https://live.adultiptv.net/interracial.m3u8","res":"1280x720","poster":"img/tv15.jpg","live":true,"views":0},{"id":"tv16","name":"拉丁","sub":"歐美成人台","group":"歐美","url":"https://live.adultiptv.net/latina.m3u8","res":"1280x720","poster":"img/tv16.jpg","live":true,"views":0},{"id":"tv17","name":"女同","sub":"歐美成人台","group":"歐美","url":"https://live.adultiptv.net/lesbian.m3u8","res":"1280x720","poster":"img/tv17.jpg","live":true,"views":0},{"id":"tv18","name":"熟女","sub":"歐美成人台","group":"歐美","url":"https://live.adultiptv.net/milf.m3u8","res":"1280x720","poster":"img/tv18.jpg","live":true,"views":0},{"id":"tv19","name":"女優","sub":"歐美成人台","group":"歐美","url":"https://live.adultiptv.net/pornstar.m3u8","res":"1280x720","poster":"img/tv19.jpg","live":true,"views":0},{"id":"tv20","name":"第一視角","sub":"歐美成人台","group":"歐美","url":"https://live.adultiptv.net/pov.m3u8","res":"1280x720","poster":"img/tv20.jpg","live":true,"views":0},{"id":"tv21","name":"粗暴","sub":"歐美成人台","group":"歐美","url":"https://live.adultiptv.net/rough.m3u8","res":"1280x720","poster":"img/tv21.jpg","live":true,"views":0},{"id":"tv22","name":"俄羅斯","sub":"歐美成人台","group":"歐美","url":"https://live.adultiptv.net/russian.m3u8","res":"1280x720","poster":"img/tv22.jpg","live":true,"views":0},{"id":"tv23","name":"三人行","sub":"歐美成人台","group":"歐美","url":"https://live.adultiptv.net/threesome.m3u8","res":"1280x720","poster":"img/tv23.jpg","live":true,"views":0},{"id":"tv24","name":"實時攝像頭","sub":"歐美成人台","group":"歐美","url":"https://live.adultiptv.net/livecams.m3u8","res":"1280x720","poster":"img/tv24.jpg","live":true,"views":0},{"id":"cam158113576","name":"yukiDX","sub":"日系主播","group":"日本","url":"https://edge-hls.doppiocdn.com/hls/158113576/master/158113576.m3u8","res":"640,480","poster":"img/cam158113576.jpg","live":true,"views":1537},{"id":"cam260896817","name":"SUxMIxRE","sub":"日系主播","group":"日本","url":"https://edge-hls.doppiocdn.com/hls/260896817/master/260896817.m3u8","res":"640,480","poster":"img/cam260896817.jpg","live":true,"views":576},{"id":"cam206626066","name":"MIZUKI88888","sub":"日系主播","group":"日本","url":"https://edge-hls.doppiocdn.com/hls/206626066/master/206626066.m3u8","res":"640,480","poster":"img/cam206626066.jpg","live":true,"views":312},{"id":"cam235545946","name":"Dona020","sub":"日系主播","group":"日本","url":"https://edge-hls.doppiocdn.com/hls/235545946/master/235545946.m3u8","res":"640,480","poster":"img/cam235545946.jpg","live":true,"views":163},{"id":"cam223879409","name":"yura_ra_ra","sub":"日系主播","group":"日本","url":"https://edge-hls.doppiocdn.com/hls/223879409/master/223879409.m3u8","res":"640,480","poster":"img/cam223879409.jpg","live":true,"views":219},{"id":"cam218103339","name":"Hanachan_Gcup_","sub":"日系主播","group":"日本","url":"https://edge-hls.doppiocdn.com/hls/218103339/master/218103339.m3u8","res":"640,480","poster":"img/cam218103339.jpg","live":true,"views":184},{"id":"cam287919750","name":"reichan__","sub":"日系主播","group":"日本","url":"https://edge-hls.doppiocdn.com/hls/287919750/master/287919750.m3u8","res":"640,480","poster":"img/cam287919750.jpg","live":true,"views":261},{"id":"cam167360408","name":"_usya_2525","sub":"日系主播","group":"日本","url":"https://edge-hls.doppiocdn.com/hls/167360408/master/167360408.m3u8","res":"640,480","poster":"img/cam167360408.jpg","live":true,"views":48},{"id":"cam244539002","name":"sakurako_ch_jpn","sub":"日系主播","group":"日本","url":"https://edge-hls.doppiocdn.com/hls/244539002/master/244539002.m3u8","res":"640,480","poster":"img/cam244539002.jpg","live":true,"views":201},{"id":"cam256682182","name":"shino_n642","sub":"日系主播","group":"日本","url":"https://edge-hls.doppiocdn.com/hls/256682182/master/256682182.m3u8","res":"640,480","poster":"img/cam256682182.jpg","live":true,"views":26},{"id":"cam290539196","name":"__bibichan__","sub":"日系主播","group":"日本","url":"https://edge-hls.doppiocdn.com/hls/290539196/master/290539196.m3u8","res":"640,480","poster":"img/cam290539196.jpg","live":true,"views":95},{"id":"cam226780931","name":"jura_xxx","sub":"日系主播","group":"日本","url":"https://edge-hls.doppiocdn.com/hls/226780931/master/226780931.m3u8","res":"640,480","poster":"img/cam226780931.jpg","live":true,"views":107},{"id":"cam255539656","name":"Luna_honey7","sub":"日系主播","group":"日本","url":"https://edge-hls.doppiocdn.com/hls/255539656/master/255539656.m3u8","res":"640,480","poster":"img/cam255539656.jpg","live":true,"views":45},{"id":"cam287714426","name":"nanachan_7","sub":"日系主播","group":"日本","url":"https://edge-hls.doppiocdn.com/hls/287714426/master/287714426.m3u8","res":"640,480","poster":"img/cam287714426.jpg","live":true,"views":42},{"id":"cam175179293","name":"ASUKA_ch","sub":"日系主播","group":"日本","url":"https://edge-hls.doppiocdn.com/hls/175179293/master/175179293.m3u8","res":"640,480","poster":"img/cam175179293.jpg","live":true,"views":2619},{"id":"cam218382580","name":"-barbapapa-","sub":"日系主播","group":"日本","url":"https://edge-hls.doppiocdn.com/hls/218382580/master/218382580.m3u8","res":"640,480","poster":"img/cam218382580.jpg","live":true,"views":218},{"id":"cam221502738","name":"ramu-mero","sub":"日系主播","group":"日本","url":"https://edge-hls.doppiocdn.com/hls/221502738/master/221502738.m3u8","res":"640,480","poster":"img/cam221502738.jpg","live":true,"views":33},{"id":"cam122457947","name":"MAOchaso","sub":"日系主播","group":"日本","url":"https://edge-hls.doppiocdn.com/hls/122457947/master/122457947.m3u8","res":"640,480","poster":"img/cam122457947.jpg","live":true,"views":154},{"id":"cam183081916","name":"tequila_09","sub":"日系主播","group":"日本","url":"https://edge-hls.doppiocdn.com/hls/183081916/master/183081916.m3u8","res":"640,480","poster":"img/cam183081916.jpg","live":true,"views":49},{"id":"cam143392735","name":"-Jun_juun-","sub":"日系主播","group":"日本","url":"https://edge-hls.doppiocdn.com/hls/143392735/master/143392735.m3u8","res":"640,480","poster":"img/cam143392735.jpg","live":true,"views":43},{"id":"cam278928099","name":"emiri_jpn","sub":"日系主播","group":"日本","url":"https://edge-hls.doppiocdn.com/hls/278928099/master/278928099.m3u8","res":"640,480","poster":"img/cam278928099.jpg","live":true,"views":31},{"id":"cam125310980","name":"AD886688","sub":"華語主播","group":"台灣・華語","url":"https://edge-hls.doppiocdn.com/hls/125310980/master/125310980.m3u8","res":"640,480","poster":"img/cam125310980.jpg","live":true,"views":714},{"id":"cam287371754","name":"ruirui77","sub":"華語主播","group":"台灣・華語","url":"https://edge-hls.doppiocdn.com/hls/287371754/master/287371754.m3u8","res":"640,480","poster":"img/cam287371754.jpg","live":true,"views":698},{"id":"cam276635416","name":"YaYa-168","sub":"華語主播","group":"台灣・華語","url":"https://edge-hls.doppiocdn.com/hls/276635416/master/276635416.m3u8","res":"640,480","poster":"img/cam276635416.jpg","live":true,"views":343},{"id":"cam274919849","name":"xiaojingling1122","sub":"華語主播","group":"台灣・華語","url":"https://edge-hls.doppiocdn.com/hls/274919849/master/274919849.m3u8","res":"640,480","poster":"img/cam274919849.jpg","live":true,"views":739},{"id":"cam286538031","name":"momo-anqi","sub":"華語主播","group":"台灣・華語","url":"https://edge-hls.doppiocdn.com/hls/286538031/master/286538031.m3u8","res":"640,480","poster":"img/cam286538031.jpg","live":true,"views":836},{"id":"cam265298647","name":"Princess_Fifi","sub":"華語主播","group":"台灣・華語","url":"https://edge-hls.doppiocdn.com/hls/265298647/master/265298647.m3u8","res":"640,480","poster":"img/cam265298647.jpg","live":true,"views":223},{"id":"cam181671623","name":"juzi1213","sub":"華語主播","group":"台灣・華語","url":"https://edge-hls.doppiocdn.com/hls/181671623/master/181671623.m3u8","res":"640,480","poster":"img/cam181671623.jpg","live":true,"views":129},{"id":"cam256819146","name":"huihui_520","sub":"華語主播","group":"台灣・華語","url":"https://edge-hls.doppiocdn.com/hls/256819146/master/256819146.m3u8","res":"640,480","poster":"img/cam256819146.jpg","live":true,"views":193},{"id":"cam158735570","name":"-XunMengLong-","sub":"華語主播","group":"台灣・華語","url":"https://edge-hls.doppiocdn.com/hls/158735570/master/158735570.m3u8","res":"640,480","poster":"img/cam158735570.jpg","live":true,"views":208},{"id":"cam281896267","name":"zhizhi03","sub":"華語主播","group":"台灣・華語","url":"https://edge-hls.doppiocdn.com/hls/281896267/master/281896267.m3u8","res":"640,480","poster":"img/cam281896267.jpg","live":true,"views":385},{"id":"cam286030762","name":"Jiemeihua","sub":"華語主播","group":"台灣・華語","url":"https://edge-hls.doppiocdn.com/hls/286030762/master/286030762.m3u8","res":"640,480","poster":"img/cam286030762.jpg","live":true,"views":144},{"id":"cam246888621","name":"Xiaoyu-99","sub":"華語主播","group":"台灣・華語","url":"https://edge-hls.doppiocdn.com/hls/246888621/master/246888621.m3u8","res":"640,480","poster":"img/cam246888621.jpg","live":true,"views":27},{"id":"cam289268124","name":"LIANGDUN","sub":"華語主播","group":"台灣・華語","url":"https://edge-hls.doppiocdn.com/hls/289268124/master/289268124.m3u8","res":"640,480","poster":"img/cam289268124.jpg","live":true,"views":76},{"id":"cam232373568","name":"Chenchen_666","sub":"華語主播","group":"台灣・華語","url":"https://edge-hls.doppiocdn.com/hls/232373568/master/232373568.m3u8","res":"640,480","poster":"img/cam232373568.jpg","live":true,"views":243},{"id":"cam238610813","name":"sky94210","sub":"華語主播","group":"台灣・華語","url":"https://edge-hls.doppiocdn.com/hls/238610813/master/238610813.m3u8","res":"640,480","poster":"img/cam238610813.jpg","live":true,"views":18},{"id":"cam189387750","name":"Yuyouwei-","sub":"華語主播","group":"台灣・華語","url":"https://edge-hls.doppiocdn.com/hls/189387750/master/189387750.m3u8","res":"640,480","poster":"img/cam189387750.jpg","live":true,"views":209},{"id":"cam160401763","name":"-ov-er-","sub":"華語主播","group":"台灣・華語","url":"https://edge-hls.doppiocdn.com/hls/160401763/master/160401763.m3u8","res":"640,480","poster":"img/cam160401763.jpg","live":true,"views":389},{"id":"cam281075960","name":"beautiful168","sub":"華語主播","group":"台灣・華語","url":"https://edge-hls.doppiocdn.com/hls/281075960/master/281075960.m3u8","res":"640,480","poster":"img/cam281075960.jpg","live":true,"views":339},{"id":"cam279622880","name":"SK5152","sub":"華語主播","group":"台灣・華語","url":"https://edge-hls.doppiocdn.com/hls/279622880/master/279622880.m3u8","res":"640,480","poster":"img/cam279622880.jpg","live":true,"views":14},{"id":"cam213080084","name":"Emma-06","sub":"華語主播","group":"台灣・華語","url":"https://edge-hls.doppiocdn.com/hls/213080084/master/213080084.m3u8","res":"640,480","poster":"img/cam213080084.jpg","live":true,"views":122},{"id":"cam215996367","name":"yigbg14","sub":"華語主播","group":"台灣・華語","url":"https://edge-hls.doppiocdn.com/hls/215996367/master/215996367.m3u8","res":"640,480","poster":"img/cam215996367.jpg","live":true,"views":391},{"id":"cam145311261","name":"JoooJo_","sub":"華語主播","group":"台灣・華語","url":"https://edge-hls.doppiocdn.com/hls/145311261/master/145311261.m3u8","res":"640,480","poster":"img/cam145311261.jpg","live":true,"views":197},{"id":"cam206236901","name":"fox-yiyi","sub":"華語主播","group":"台灣・華語","url":"https://edge-hls.doppiocdn.com/hls/206236901/master/206236901.m3u8","res":"640,480","poster":"img/cam206236901.jpg","live":true,"views":108},{"id":"cam284386339","name":"baobao-3344","sub":"華語主播","group":"台灣・華語","url":"https://edge-hls.doppiocdn.com/hls/284386339/master/284386339.m3u8","res":"640,480","poster":"img/cam284386339.jpg","live":true,"views":404},{"id":"cam125195669","name":"Yaooooo-Y","sub":"華語主播","group":"台灣・華語","url":"https://edge-hls.doppiocdn.com/hls/125195669/master/125195669.m3u8","res":"640,480","poster":"img/cam125195669.jpg","live":true,"views":116},{"id":"cam255995739","name":"Dian-Sex","sub":"華語主播","group":"台灣・華語","url":"https://edge-hls.doppiocdn.com/hls/255995739/master/255995739.m3u8","res":"640,480","poster":"img/cam255995739.jpg","live":true,"views":255},{"id":"cam258803058","name":"RoseGirl888","sub":"華語主播","group":"台灣・華語","url":"https://edge-hls.doppiocdn.com/hls/258803058/master/258803058.m3u8","res":"640,480","poster":"img/cam258803058.jpg","live":true,"views":221},{"id":"cam275625702","name":"Laosilaisi-xx","sub":"華語主播","group":"台灣・華語","url":"https://edge-hls.doppiocdn.com/hls/275625702/master/275625702.m3u8","res":"640,480","poster":"img/cam275625702.jpg","live":true,"views":197},{"id":"cam282063774","name":"yikecaomei","sub":"華語主播","group":"台灣・華語","url":"https://edge-hls.doppiocdn.com/hls/282063774/master/282063774.m3u8","res":"640,480","poster":"img/cam282063774.jpg","live":true,"views":29},{"id":"cam279573413","name":"fengjiao20","sub":"華語主播","group":"台灣・華語","url":"https://edge-hls.doppiocdn.com/hls/279573413/master/279573413.m3u8","res":"640,480","poster":"img/cam279573413.jpg","live":true,"views":57},{"id":"cam208310207","name":"Meruru-","sub":"華語主播","group":"台灣・華語","url":"https://edge-hls.doppiocdn.com/hls/208310207/master/208310207.m3u8","res":"640,480","poster":"img/cam208310207.jpg","live":true,"views":167},{"id":"cam163955134","name":"Asian_Asami","sub":"亞洲主播","group":"亞洲","url":"https://edge-hls.doppiocdn.com/hls/163955134/master/163955134.m3u8","res":"640,480","poster":"img/cam163955134.jpg","live":true,"views":4695},{"id":"cam275185664","name":"xiaomaomi0123","sub":"亞洲主播","group":"亞洲","url":"https://edge-hls.doppiocdn.com/hls/275185664/master/275185664.m3u8","res":"640,480","poster":"img/cam275185664.jpg","live":true,"views":1439},{"id":"cam272921449","name":"Cute_emma","sub":"亞洲主播","group":"亞洲","url":"https://edge-hls.doppiocdn.com/hls/272921449/master/272921449.m3u8","res":"640,480","poster":"img/cam272921449.jpg","live":true,"views":34},{"id":"cam284784137","name":"mayasedusa","sub":"亞洲主播","group":"亞洲","url":"https://edge-hls.doppiocdn.com/hls/284784137/master/284784137.m3u8","res":"640,480","poster":"img/cam284784137.jpg","live":true,"views":43},{"id":"cam231964798","name":"TariLechliter","sub":"亞洲主播","group":"亞洲","url":"https://edge-hls.doppiocdn.com/hls/231964798/master/231964798.m3u8","res":"640,480","poster":"img/cam231964798.jpg","live":true,"views":480},{"id":"cam208423390","name":"_LoveBugs_","sub":"亞洲主播","group":"亞洲","url":"https://edge-hls.doppiocdn.com/hls/208423390/master/208423390.m3u8","res":"640,480","poster":"img/cam208423390.jpg","live":true,"views":4178},{"id":"cam250184379","name":"MelancholyChronicles","sub":"亞洲主播","group":"亞洲","url":"https://edge-hls.doppiocdn.com/hls/250184379/master/250184379.m3u8","res":"640,480","poster":"img/cam250184379.jpg","live":true,"views":582},{"id":"cam288241497","name":"baybik","sub":"亞洲主播","group":"亞洲","url":"https://edge-hls.doppiocdn.com/hls/288241497/master/288241497.m3u8","res":"640,480","poster":"img/cam288241497.jpg","live":true,"views":20},{"id":"cam276037873","name":"minasaaii","sub":"亞洲主播","group":"亞洲","url":"https://edge-hls.doppiocdn.com/hls/276037873/master/276037873.m3u8","res":"640,480","poster":"img/cam276037873.jpg","live":true,"views":22},{"id":"cam236201430","name":"yenai_xx","sub":"亞洲主播","group":"亞洲","url":"https://edge-hls.doppiocdn.com/hls/236201430/master/236201430.m3u8","res":"640,480","poster":"img/cam236201430.jpg","live":true,"views":1167},{"id":"cam285518143","name":"menghan011","sub":"亞洲主播","group":"亞洲","url":"https://edge-hls.doppiocdn.com/hls/285518143/master/285518143.m3u8","res":"640,480","poster":"img/cam285518143.jpg","live":true,"views":782},{"id":"cam159047981","name":"JoyFulLicss","sub":"亞洲主播","group":"亞洲","url":"https://edge-hls.doppiocdn.com/hls/159047981/master/159047981.m3u8","res":"640,480","poster":"img/cam159047981.jpg","live":true,"views":328},{"id":"cam285819218","name":"HayleyArau","sub":"亞洲主播","group":"亞洲","url":"https://edge-hls.doppiocdn.com/hls/285819218/master/285819218.m3u8","res":"640,480","poster":"img/cam285819218.jpg","live":true,"views":9},{"id":"cam282333042","name":"AsianTeenXXX","sub":"亞洲主播","group":"亞洲","url":"https://edge-hls.doppiocdn.com/hls/282333042/master/282333042.m3u8","res":"640,480","poster":"img/cam282333042.jpg","live":true,"views":61},{"id":"cam151166129","name":"Kim_SLO","sub":"亞洲主播","group":"亞洲","url":"https://edge-hls.doppiocdn.com/hls/151166129/master/151166129.m3u8","res":"640,480","poster":"img/cam151166129.jpg","live":true,"views":109},{"id":"cam223542680","name":"Mmo66","sub":"亞洲主播","group":"亞洲","url":"https://edge-hls.doppiocdn.com/hls/223542680/master/223542680.m3u8","res":"640,480","poster":"img/cam223542680.jpg","live":true,"views":504},{"id":"cam286874626","name":"_SHEHANI_","sub":"亞洲主播","group":"亞洲","url":"https://edge-hls.doppiocdn.com/hls/286874626/master/286874626.m3u8","res":"640,480","poster":"img/cam286874626.jpg","live":true,"views":506},{"id":"cam197346384","name":"thedaynahoney","sub":"亞洲主播","group":"亞洲","url":"https://edge-hls.doppiocdn.com/hls/197346384/master/197346384.m3u8","res":"640,480","poster":"img/cam197346384.jpg","live":true,"views":23},{"id":"cam218040000","name":"STRIP_GLOW","sub":"亞洲主播","group":"亞洲","url":"https://edge-hls.doppiocdn.com/hls/218040000/master/218040000.m3u8","res":"640,480","poster":"img/cam218040000.jpg","live":true,"views":463},{"id":"cam288938708","name":"Tequila_Biscardi","sub":"亞洲主播","group":"亞洲","url":"https://edge-hls.doppiocdn.com/hls/288938708/master/288938708.m3u8","res":"640,480","poster":"img/cam288938708.jpg","live":true,"views":17},{"id":"cam270812654","name":"sweethairypussyxxx","sub":"亞洲主播","group":"亞洲","url":"https://edge-hls.doppiocdn.com/hls/270812654/master/270812654.m3u8","res":"640,480","poster":"img/cam270812654.jpg","live":true,"views":2},{"id":"cam220523363","name":"Lissa_kissyou","sub":"亞洲主播","group":"亞洲","url":"https://edge-hls.doppiocdn.com/hls/220523363/master/220523363.m3u8","res":"640,480","poster":"img/cam220523363.jpg","live":true,"views":43},{"id":"cam289950532","name":"liona_moon","sub":"亞洲主播","group":"亞洲","url":"https://edge-hls.doppiocdn.com/hls/289950532/master/289950532.m3u8","res":"640,480","poster":"img/cam289950532.jpg","live":true,"views":9},{"id":"cam290222941","name":"Flawless_Asia","sub":"亞洲主播","group":"亞洲","url":"https://edge-hls.doppiocdn.com/hls/290222941/master/290222941.m3u8","res":"640,480","poster":"img/cam290222941.jpg","live":true,"views":46},{"id":"cam193551651","name":"EditaBails","sub":"亞洲主播","group":"亞洲","url":"https://edge-hls.doppiocdn.com/hls/193551651/master/193551651.m3u8","res":"640,480","poster":"img/cam193551651.jpg","live":true,"views":108},{"id":"cam51507717","name":"Alexa_Girl1","sub":"亞洲主播","group":"亞洲","url":"https://edge-hls.doppiocdn.com/hls/51507717/master/51507717.m3u8","res":"640,480","poster":"img/cam51507717.jpg","live":true,"views":140},{"id":"cam290155553","name":"ElfyAsia","sub":"亞洲主播","group":"亞洲","url":"https://edge-hls.doppiocdn.com/hls/290155553/master/290155553.m3u8","res":"640,480","poster":"img/cam290155553.jpg","live":true,"views":1},{"id":"cam272071835","name":"tiantian52014","sub":"亞洲主播","group":"亞洲","url":"https://edge-hls.doppiocdn.com/hls/272071835/master/272071835.m3u8","res":"640,480","poster":"img/cam272071835.jpg","live":true,"views":189},{"id":"cam243574634","name":"DaizyDanny","sub":"亞洲主播","group":"亞洲","url":"https://edge-hls.doppiocdn.com/hls/243574634/master/243574634.m3u8","res":"640,480","poster":"img/cam243574634.jpg","live":true,"views":775},{"id":"cam289160943","name":"KamiSharpes","sub":"亞洲主播","group":"亞洲","url":"https://edge-hls.doppiocdn.com/hls/289160943/master/289160943.m3u8","res":"640,480","poster":"img/cam289160943.jpg","live":true,"views":28},{"id":"cam186907375","name":"LewdFoxy_VT","sub":"亞洲主播","group":"亞洲","url":"https://edge-hls.doppiocdn.com/hls/186907375/master/186907375.m3u8","res":"640,480","poster":"img/cam186907375.jpg","live":true,"views":92},{"id":"cam286888094","name":"StephanieMaldonado","sub":"亞洲主播","group":"亞洲","url":"https://edge-hls.doppiocdn.com/hls/286888094/master/286888094.m3u8","res":"640,480","poster":"img/cam286888094.jpg","live":true,"views":59},{"id":"cam289318212","name":"KeraHewgley","sub":"亞洲主播","group":"亞洲","url":"https://edge-hls.doppiocdn.com/hls/289318212/master/289318212.m3u8","res":"640,480","poster":"img/cam289318212.jpg","live":true,"views":28},{"id":"cam278341935","name":"duovibess","sub":"亞洲主播","group":"亞洲","url":"https://edge-hls.doppiocdn.com/hls/278341935/master/278341935.m3u8","res":"640,480","poster":"img/cam278341935.jpg","live":true,"views":712},{"id":"cam290275408","name":"katsuragi_","sub":"亞洲主播","group":"亞洲","url":"https://edge-hls.doppiocdn.com/hls/290275408/master/290275408.m3u8","res":"640,480","poster":"img/cam290275408.jpg","live":true,"views":16},{"id":"cam286210692","name":"MasillesUreni","sub":"亞洲主播","group":"亞洲","url":"https://edge-hls.doppiocdn.com/hls/286210692/master/286210692.m3u8","res":"640,480","poster":"img/cam286210692.jpg","live":true,"views":75}]'''


class Spider(object):
    """TVBox Python 蜘蛛標準實現。"""

    _cache = {"data": None, "ts": 0.0, "base": "", "snapshot": False}
    _cooldown = {}

    # ------------------------------------------------------------------ 生命週期
    def __init__(self, extend=""):
        self._cfg = dict(DEFAULT_CFG)
        self.extend = extend or ""
        self.init(self.extend)

    def init(self, extend=""):
        self.extend = "" if extend is None else extend
        cfg = dict(DEFAULT_CFG)
        if isinstance(extend, dict):                 # 殼子直接傳 dict 也吃得下
            cfg.update(extend)
        else:
            cfg.update(self._parse_extend(str(extend)))
        cfg["domains"] = self._norm_domains(cfg.get("domain") or "")
        try:
            cfg["page_size"] = max(1, int(cfg.get("page_size") or 36))
        except Exception:
            cfg["page_size"] = 36
        try:
            cfg["timeout"] = max(1, float(cfg.get("timeout") or 10))
        except Exception:
            cfg["timeout"] = 10
        try:
            cfg["ttl"] = max(0, float(cfg.get("ttl") if cfg.get("ttl") is not None else 300))
        except Exception:
            cfg["ttl"] = 300
        cfg["snapshot"] = self._as_bool(cfg.get("snapshot"), True)
        self._cfg = cfg
        return self

    def getName(self):
        return "ZakaLive"

    # ------------------------------------------------------------------ 配置解析
    @staticmethod
    def _parse_extend(extend):
        ext = (extend or "").strip()
        if not ext:
            return {}
        if ext[:1] in "{[":
            try:
                obj = json.loads(ext)
            except Exception:
                obj = None
            if isinstance(obj, dict):
                return dict(obj)
        if "=" in ext:
            out = {}
            for kv in re.split(r"[&\n;]+", ext):
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    k = k.strip()
                    if k:
                        out[k] = v.strip()
            if out:
                return out
        return {"domain": ext}

    @staticmethod
    def _as_bool(val, default=True):
        """extend 裡 snapshot=0/false/off 要當成關閉，別被字符串的真值騙了。"""
        if val is None:
            return default
        if isinstance(val, bool):
            return val
        text = str(val).strip().lower()
        if text in ("0", "false", "no", "off", "none", ""):
            return False
        if text in ("1", "true", "yes", "on"):
            return True
        return default

    @staticmethod
    def _norm_domains(raw):
        out = []
        for host in re.split(r"[\s,，;|]+", str(raw or "")):
            host = host.strip().rstrip("/")
            if not host:
                continue
            if not host.startswith(("http://", "https://")):
                host = "https://" + host
            if host not in out:
                out.append(host)
        return out

    def _bases(self):
        ordered = list(self._cfg.get("domains") or [])
        for h in SITE_BASES:
            if h not in ordered:
                ordered.append(h)
        last = self._cache.get("base")
        if last and last in ordered:
            ordered.remove(last)
            ordered.insert(0, last)
        return ordered

    def _page_size(self):
        return self._cfg["page_size"]

    def _headers(self):
        h = {"User-Agent": self._cfg.get("ua") or UA}
        ref = (self._cfg.get("referer") or "").strip()
        if ref:
            h["Referer"] = ref
        return h

    # ------------------------------------------------------------------ 網絡
    def _http(self, url):
        """取回 UTF-8 文本，任何異常都返回 None，不向上拋。"""
        timeout = self._cfg["timeout"]
        try:
            if requests is not None:
                r = requests.get(url, headers=self._headers(), timeout=timeout)
                if r.status_code != 200:
                    return None
                return (r.content or b"").decode("utf-8", "replace")
            req = urllib.request.Request(url, headers=self._headers())
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", "replace")
        except Exception:
            return None

    def _fetch(self, path):
        """按域名池輪詢，只認 JSON；HTML 攔截頁當失敗。"""
        for base in self._bases():
            if self._cooldown.get(base, 0) > time.time():
                continue
            raw = self._http(base + path)
            text = (raw or "").strip()
            if not text or text[:1] not in "[{":
                self._cooldown[base] = time.time() + COOLDOWN
                continue
            try:
                obj = json.loads(text)
            except Exception:
                self._cooldown[base] = time.time() + COOLDOWN
                continue
            self._cooldown.pop(base, None)
            self._cache["base"] = base
            return obj, base
        return None, None

    # ------------------------------------------------------------------ 數據
    @staticmethod
    def _norm(ch, base):
        if not isinstance(ch, dict):
            return None
        name = str(ch.get("name") or "").strip()
        url = str(ch.get("url") or "").strip()
        if not name or not url:
            return None
        poster = str(ch.get("poster") or "").strip()
        if poster and not poster.startswith(("http://", "https://")):
            prefix = base.rstrip("/") + "/"
            if poster.startswith("//"):
                poster = "https:" + poster
            else:
                poster = prefix + poster.lstrip("/")
        return {
            "id": str(ch.get("id") or name).strip(),
            "name": name,
            "sub": str(ch.get("sub") or "").strip(),
            "group": str(ch.get("group") or "未分組").strip() or "未分組",
            "url": url,
            "res": str(ch.get("res") or "").strip(),
            "poster": poster,
            "type": str(ch.get("type") or "").strip().lower(),
            "hevc": bool(ch.get("hevc")),
            "views": ch.get("views") or 0,
        }

    def _load(self):
        now = time.time()
        c = self.__class__._cache
        if c["data"] is not None and (now - c["ts"]) < self._cfg["ttl"]:
            return c["data"], c["base"], c["snapshot"]

        obj, base = self._fetch(DATA_PATH)
        if isinstance(obj, dict):
            obj = obj.get("data") or obj.get("list") or obj.get("items") or []
        data, snap = [], False
        if isinstance(obj, list) and obj:
            for ch in obj:
                item = self._norm(ch, base or SITE_BASES[0])
                if item:
                    data.append(item)

        if not data and self._cfg.get("snapshot", True):
            try:
                raw = json.loads(SNAPSHOT)
            except Exception:
                raw = []
            for ch in raw:
                item = self._norm(ch, SITE_BASES[0])
                if item:
                    data.append(item)
            snap = bool(data)
            base = SITE_BASES[0]

        c.update({"data": data, "ts": now, "base": base or SITE_BASES[0], "snapshot": snap})
        return c["data"], c["base"], c["snapshot"]

    @staticmethod
    def _groups(chs):
        out = []
        for c in chs:
            if c["group"] not in out:
                out.append(c["group"])
        return out

    @staticmethod
    def _interleave(chs, limit):
        """按分組輪流取樣，首頁不會被某一個分組刷滿。"""
        groups = Spider._groups(chs)
        buckets = {g: [c for c in chs if c["group"] == g] for g in groups}
        out, idx = [], 0
        while len(out) < limit:
            added = False
            for g in groups:
                if len(out) >= limit:
                    break
                if idx < len(buckets[g]):
                    out.append(buckets[g][idx])
                    added = True
            if not added:
                break
            idx += 1
        return out

    @staticmethod
    def _remarks(c):
        bits = [c["group"]]
        if c["res"]:
            bits.append(c["res"])
        if c["hevc"]:
            bits.append("H.265")
        return " · ".join(bits)

    def _vod(self, c):
        return {
            "vod_id": c["id"],
            "vod_name": c["name"],
            "vod_pic": c["poster"],
            "vod_remarks": self._remarks(c),
            "vod_year": "",
            "vod_area": c["group"],
            "vod_actor": c["sub"],
            "type_name": c["group"],
        }

    def _vod_list(self, chs):
        return [self._vod(c) for c in chs]

    # ------------------------------------------------------------------ 診斷條目
    def _diag_text(self):
        bases = "、".join(self._bases())
        return (
            "接口不通：%s 的 /data.json 沒拿到 JSON。\n\n"
            "這個站沒有服務端 API，頻道表就是同源靜態檔 /data.json，"
            "分類、搜尋、分頁都在前端 app.js 裡做，所以取不到它就整站空白。\n\n"
            "三種處理方式：\n"
            "1) 換域名：在站點 ext 裡填一條能通的完整域名，支援多條用逗號隔開；\n"
            "2) 掛代理：殼子支持代理的直接開，或用 ext 填反代後綴；\n"
            "3) 等站點恢復：現在顯示的是內置快照（2026-11-17 抓的 130 條），"
            "地址會失效，能聯網時會自動換回線上數據。\n\n"
            "當前嘗試過的域名：%s" % (SITE_BASES[0], bases)
        )

    def _diag_vod(self):
        return {
            "vod_id": DIAG_ID,
            "vod_name": DIAG_NAME,
            "vod_pic": "",
            "vod_remarks": "看修法",
            "vod_year": "",
            "vod_area": "提示",
            "vod_actor": "",
            "vod_content": self._diag_text(),
            "vod_play_from": "",
            "vod_play_url": "",
        }

    # ------------------------------------------------------------------ TVBox 接口
    def homeContent(self, filter=None):
        chs, _base, snap = self._load()
        classes = [{"type_id": "all", "type_name": "全部"}]
        classes += [{"type_id": g, "type_name": g} for g in self._groups(chs)]
        videos = self._vod_list(self._interleave(chs, self._page_size()))
        if snap or not chs:
            videos.insert(0, self._diag_vod())
        return {"class": classes, "filters": {}, "list": videos}

    def homeVideoContent(self):
        chs, _base, snap = self._load()
        videos = self._vod_list(self._interleave(chs, self._page_size()))
        if snap or not chs:
            videos.insert(0, self._diag_vod())
        return {"list": videos}

    def categoryContent(self, tid, page=1, filter=None, ext=None):
        chs, _base, _snap = self._load()
        tid = str(tid or "").strip()
        pool = list(chs)
        if tid not in ("", "all", "全部", "hot", "最新"):
            pool = [c for c in chs if c["group"] == tid]
            if not pool and "%" in tid:
                try:
                    alt = urllib.parse.unquote(tid)
                except Exception:
                    alt = tid
                pool = [c for c in chs if c["group"] == alt]
        total = len(pool)
        ps = self._page_size()
        try:
            pg = int(page)
        except Exception:
            pg = 1
        pg = max(1, pg)
        start = (pg - 1) * ps
        return {
            "page": pg,
            "pagecount": max(1, (total + ps - 1) // ps),
            "limit": ps,
            "total": total,
            "list": self._vod_list(pool[start:start + ps]),
        }

    def searchContent(self, key, quick=False, pg=1):
        chs, _base, _snap = self._load()
        kw = str(key or "").strip().lower()
        pool = []
        for c in chs:
            if not kw or (kw in c["name"].lower()
                          or kw in c["sub"].lower()
                          or kw in c["group"].lower()):
                pool.append(c)
        total = len(pool)
        size = self._page_size()
        try:
            page = int(pg)
        except Exception:
            page = 1
        page = max(1, page)
        start = (page - 1) * size
        return {
            "page": page,
            "pagecount": max(1, (total + size - 1) // size),
            "limit": size,
            "total": total,
            "list": self._vod_list(pool[start:start + size]),
        }

    def detailContent(self, ids):
        chs, _base, _snap = self._load()
        if isinstance(ids, (str, int)):
            ids = [ids]
        index = {c["id"]: c for c in chs}
        out = []
        for vid in (ids or []):
            vid = str(vid).strip()
            if vid == DIAG_ID:
                out.append(self._diag_vod())
                continue
            ch = index.get(vid)
            if not ch:
                continue
            base_name = ch["name"].split("·")[0].split("・")[0].strip()
            alt = None
            for c in chs:
                if c["id"] == ch["id"]:
                    continue
                if c["name"] in (base_name + "·備用", base_name + "·备用"):
                    alt = c
                    break
            froms = ["直播"]
            urls = ["主線" + "$" + ch["url"]]
            if alt:
                froms.append("備用")
                urls.append("備用線" + "$" + alt["url"])
            vod = self._vod(ch)
            vod.update({
                "vod_play_from": "$$$".join(froms),
                "vod_play_url": "$$$".join(urls),
                "vod_content": "\n".join([
                    "頻道：%s（%s）" % (ch["name"], ch["group"]),
                    "分類標籤：%s" % (ch["sub"] or "—"),
                    "解析度：%s%s" % (ch["res"] or "未知", " · H.265 編碼" if ch["hevc"] else ""),
                    "流類型：%s" % (ch["type"] or ("hls" if "m3u8" in ch["url"].lower() else "直連")),
                    "播放地址：%s" % ch["url"],
                    "備註：這個站是靜態頻道表，沒有單集概念，點播即開直播流；"
                    "H.265 的台在部分播放器上只能出聲，換 VLC / TiviMate 更穩。",
                ]),
            })
            out.append(vod)
        return {"list": out}

    def playerContent(self, flag, id, vipFlags=None):
        url = str(id or "").strip()
        if not url or url == DIAG_ID:
            return {"parse": 0, "playUrl": "", "url": "", "header": self._headers(), "format": ""}
        fmt = "application/vnd.apple.mpegurl" if "m3u8" in url.lower() else ""
        return {"parse": 0, "playUrl": "", "url": url,
                "header": self._headers(), "format": fmt}


# ====================================================================== 命令列
def _run_online():
    sp = Spider()
    home = sp.homeContent(False)
    print("站點：%s" % " ".join(SITE_BASES))
    print("分類：%s" % " | ".join("%s(%s)" % (c["type_name"], c["type_id"]) for c in home["class"]))
    print("首頁條目：%d" % len(home["list"]))
    for v in home["list"][:4]:
        print("   - %-18s %-14s %s" % (v["vod_name"][:18], v["vod_remarks"][:14], v["vod_pic"][:60]))
    for cls in home["class"]:
        cc = sp.categoryContent(cls["type_id"], 1, False)
        print("分類 %-8s 共 %3d 台 / %d 頁，本頁 %d 條"
              % (cls["type_name"], cc["total"], cc["pagecount"], len(cc["list"])))
    sr = sp.searchContent("台", False, 1)
    print("搜尋「台」：%d 條，首條 %s" % (sr["total"], sr["list"][0]["vod_name"] if sr["list"] else "—"))
    first = home["list"][0]["vod_id"] if home["list"] else ""
    det = sp.detailContent([first])
    if det["list"]:
        d = det["list"][0]
        print("詳情：%s / 線路 %s" % (d["vod_name"], d["vod_play_from"] or "—"))
        print("  播放：%s" % (d["vod_play_url"][:100] or "—"))
    pc = sp.playerContent("", (det["list"][0]["vod_play_url"].split("$")[-1]) if det["list"] else "", [])
    print("playerContent：parse=%s format=%s url=%s" % (pc["parse"], pc["format"] or "—", (pc["url"] or "—")[:80]))


def _run_offline():
    Spider._http = lambda self, url: SNAPSHOT
    sp = Spider()
    home = sp.homeContent(False)
    print("離線模式（只讀內置快照）：分類 %d 個，首頁 %d 條"
          % (len(home["class"]), len(home["list"])))
    det = sp.detailContent([home["list"][1]["vod_id"] if len(home["list"]) > 1 else ""])
    if det["list"]:
        print("詳情可用：%s" % det["list"][0]["vod_name"])


def _selftest():
    ok = [0]

    def chk(name, cond):
        if cond:
            ok[0] += 1
        else:
            print("FAIL %s" % name)
            raise SystemExit(1)

    raw = SNAPSHOT

    # --- 配置解析
    sp = Spider()
    chk("空 extend 走內置域名", sp._bases()[0] == SITE_BASES[0])
    chk("page_size 默認 36", sp._page_size() == 36)
    sp = Spider("https://a.example.com")
    chk("裸域名", sp._bases()[0] == "https://a.example.com")
    sp = Spider("a.example.com,")
    chk("無協議自動補 https", sp._bases()[0] == "https://a.example.com")
    sp = Spider("a.com,b.com")
    chk("多域名", sp._bases()[:2] == ["https://a.com", "https://b.com"])
    chk("內置域名兜底在後面", SITE_BASES[0] in sp._bases())
    sp = Spider("domain=https://x.cn&page_size=12&timeout=6&referer=https://r.cn/")
    chk("查詢串 page_size", sp._page_size() == 12)
    chk("查詢串 timeout", sp._cfg["timeout"] == 6)
    chk("查詢串 referer", sp._headers().get("Referer") == "https://r.cn/")
    sp = Spider('{"domain":"https://j.cn","page_size":9}')
    chk("JSON extend", sp._bases()[0] == "https://j.cn" and sp._page_size() == 9)
    sp = Spider("page_size=abc")
    chk("非法 page_size 回退 36", sp._page_size() == 36)
    sp = Spider("timeout=0")
    chk("timeout 下限 1", sp._cfg["timeout"] == 1)
    chk("getName", Spider().getName() == "ZakaLive")

    # --- 快照本身
    snap = json.loads(raw)
    chk("快照是陣列", isinstance(snap, list))
    chk("快照 130 條", len(snap) == 130)
    chk("快照字段齊全", all(k in snap[0] for k in ("id", "name", "group", "url", "poster")))
    chk("快照無重複 id", len({x["id"] for x in snap}) == 130)

    # --- 離線全鏈路
    Spider._cache = {"data": None, "ts": 0.0, "base": "", "snapshot": False}
    Spider._cooldown = {}
    Spider._http = lambda self, url: raw
    sp = Spider()
    home = sp.homeContent(False)
    chk("分類 6 個（全部+5 組）", len(home["class"]) == 6)
    chk("第一個分類是全部", home["class"][0]["type_id"] == "all")
    chk("分組齊全", sorted(c["type_id"] for c in home["class"][1:]) ==
        sorted(["台灣頻道", "日本", "台灣・華語", "歐美", "亞洲"]))
    chk("分組按線上順序", [c["type_id"] for c in home["class"][1:]] ==
        ["台灣頻道", "歐美", "日本", "台灣・華語", "亞洲"])
    chk("首頁條目 = page_size", len(home["list"]) == 36)
    chk("在線時不插診斷條目", all(v["vod_id"] != DIAG_ID for v in home["list"]))
    chk("首頁按分組輪流", len({v["type_name"] for v in home["list"][:5]}) >= 4)
    chk("封面成絕對地址", home["list"][0]["vod_pic"].startswith("https://"))
    chk("封面拼對", home["list"][0]["vod_pic"].endswith(".jpg"))
    chk("備註帶分組", "頻道" in home["list"][0]["vod_remarks"])

    hv = sp.homeVideoContent()
    chk("homeVideoContent 有 list", len(hv["list"]) == 36)

    # --- 分類
    c1 = sp.categoryContent("台灣頻道", 1, False)
    chk("台灣頻道 18 台", c1["total"] == 18)
    chk("台灣頻道 1 頁", c1["pagecount"] == 1)
    chk("台灣頻道條目數", len(c1["list"]) == 18)
    chk("全部 130 台", sp.categoryContent("all", 1, False)["total"] == 130)
    chk("全部 4 頁", sp.categoryContent("all", 1, False)["pagecount"] == 4)
    chk("第 2 頁 36 條", len(sp.categoryContent("all", 2, False)["list"]) == 36)
    chk("末頁 22 條", len(sp.categoryContent("all", 4, False)["list"]) == 22)
    chk("越界頁空列表", sp.categoryContent("all", 99, False)["list"] == [])
    chk("越界頁 page 保留", sp.categoryContent("all", 99, False)["page"] == 99)
    chk("非法 page 回 1", sp.categoryContent("all", "x", False)["page"] == 1)
    chk("未知分類空", sp.categoryContent("不存在", 1, False)["total"] == 0)
    chk("亞洲 36 台", sp.categoryContent("亞洲", 1, False)["total"] == 36)
    enc = sp.categoryContent(urllib.parse.quote("亞洲"), 1, False)
    chk("URL 編碼 tid 可解", enc["total"] == 36)
    chk("次頁不重複", sp.categoryContent("all", 2, False)["list"][0]["vod_id"] !=
        sp.categoryContent("all", 1, False)["list"][0]["vod_id"])

    # --- 搜尋
    s = sp.searchContent("台", False, 1)
    chk("搜尋有結果", s["total"] > 0)
    chk("搜尋結果命中名稱/標籤/分組",
        all("台" in (v["vod_name"] + v["vod_remarks"] + (v["vod_actor"] or "")) for v in s["list"]))
    chk("搜尋命中分組也算", s["total"] >= 1)
    chk("搜尋大小寫不敏感", sp.searchContent("yuki", False, 1)["total"] ==
        sp.searchContent("YUKI", False, 1)["total"])
    chk("搜尋空關鍵字返回全部", sp.searchContent("", False, 1)["total"] == 130)
    chk("搜尋無結果", sp.searchContent("zzzznotexist", False, 1)["total"] == 0)
    chk("搜尋可翻頁", sp.searchContent("", False, 2)["page"] == 2)
    chk("搜尋 limit", sp.searchContent("台", False, 1)["limit"] == 36)

    # --- 詳情
    d = sp.detailContent(["tw01"])
    chk("詳情單條", len(d["list"]) == 1)
    chk("詳情名稱", d["list"][0]["vod_name"] == "驚艷台")
    chk("詳情有播放線", d["list"][0]["vod_play_from"] == "直播$$$備用")
    chk("詳情兩條地址", d["list"][0]["vod_play_url"].count("$$$") == 1)
    chk("詳情地址可拆集名", all("$" in seg for seg in d["list"][0]["vod_play_url"].split("$$$")))
    chk("詳情線路數對齊", len(d["list"][0]["vod_play_from"].split("$$$")) ==
        len(d["list"][0]["vod_play_url"].split("$$$")))
    chk("詳情地址是流", ".ts" in d["list"][0]["vod_play_url"])
    chk("詳情有簡介", "播放地址" in d["list"][0]["vod_content"])
    chk("詳情字符串 id 兼容", len(sp.detailContent("tw01")["list"]) == 1)
    chk("詳情未知 id", sp.detailContent(["nope"])["list"] == [])
    chk("詳情空 ids", sp.detailContent([])["list"] == [])
    chk("詳情批量", len(sp.detailContent(["tw01", "tw03"])["list"]) == 2)
    d2 = sp.detailContent(["tw03"])
    chk("無備用只有一線", d2["list"][0]["vod_play_from"] == "直播")

    # --- 播放
    p = sp.playerContent("", "https://live.adultiptv.net/anal.m3u8", [])
    chk("m3u8 format", p["format"] == "application/vnd.apple.mpegurl")
    chk("m3u8 parse=0", p["parse"] == 0)
    chk("m3u8 帶 header", "User-Agent" in p["header"])
    p2 = sp.playerContent("", "http://1.2.3.4:25461/live/a/b/85.ts", [])
    chk("ts 不帶 format", p2["format"] == "")
    chk("ts 原樣返回", p2["url"].endswith("85.ts"))
    chk("空 id 不崩", sp.playerContent("", "", [])["url"] == "")
    p3 = sp.playerContent("", "http://x315601.serv00.net/cr.php?url=http://a/b/index.m3u8", [])
    chk("反代地址判 HLS", p3["format"] == "application/vnd.apple.mpegurl")

    # --- 嵌入快照裡的 H.265 條目
    hevc = [c for c in snap if c.get("hevc")]
    chk("快照有 H.265 條目", len(hevc) == 4)
    sp2 = Spider()
    vv = sp2.detailContent([hevc[0]["id"]])["list"][0]
    chk("H.265 詳情標註", "H.265" in vv["vod_content"])

    # --- 全域名不通時的降級
    Spider._cache = {"data": None, "ts": 0.0, "base": "", "snapshot": False}
    Spider._cooldown = {}
    Spider._http = lambda self, url: None
    sp3 = Spider()
    h3 = sp3.homeContent(False)
    chk("全不通仍有條目（快照）", len(h3["list"]) > 0)
    chk("全不通插診斷條目", h3["list"][0]["vod_id"] == DIAG_ID)
    chk("診斷條目在首位", h3["list"][0]["vod_name"] == DIAG_NAME)
    chk("診斷說明带域名", "data.json" in h3["list"][0]["vod_content"])
    chk("降級後分類還在", len(h3["class"]) == 6)
    d3 = sp3.detailContent([DIAG_ID])
    chk("診斷詳情可讀", "ext" in d3["list"][0]["vod_content"])
    chk("診斷播放不崩", sp3.playerContent("", DIAG_ID, [])["url"] == "")

    # --- HTML 攔截頁判死
    Spider._cache = {"data": None, "ts": 0.0, "base": "", "snapshot": False}
    Spider._cooldown = {}
    Spider._http = lambda self, url: "<html><body>blocked</body></html>"
    sp4 = Spider()
    chk("HTML 攔截走快照", len(sp4.homeContent(False)["list"]) > 1)
    chk("HTML 攔截進冷卻", len(Spider._cooldown) > 0)

    # --- 壞 JSON
    Spider._cache = {"data": None, "ts": 0.0, "base": "", "snapshot": False}
    Spider._cooldown = {}
    Spider._http = lambda self, url: "{broken"
    chk("壞 JSON 走快照", len(Spider().homeContent(False)["list"]) > 1)

    # --- 關掉快照則只剩診斷
    Spider._cache = {"data": None, "ts": 0.0, "base": "", "snapshot": False}
    Spider._cooldown = {}
    Spider._http = lambda self, url: None
    sp5 = Spider("snapshot=0")
    h5 = sp5.homeContent(False)
    chk("關快照後只有診斷條", [v["vod_id"] for v in h5["list"]] == [DIAG_ID])

    # --- 緩存
    Spider._cache = {"data": None, "ts": 0.0, "base": "", "snapshot": False}
    Spider._cooldown = {}
    calls = {"n": 0}

    def _count(self, url):
        calls["n"] += 1
        return raw
    Spider._http = _count
    sp6 = Spider("ttl=300")
    sp6.homeContent(False)
    sp6.categoryContent("all", 1, False)
    sp6.searchContent("", False, 1)
    chk("ttl 內只取一次", calls["n"] == 1)
    sp7 = Spider("ttl=0")
    sp7.homeContent(False)
    sp7.homeContent(False)
    chk("ttl=0 每次重取", calls["n"] == 3)

    # --- 域名輪換：第一個死、第二個活
    Spider._cache = {"data": None, "ts": 0.0, "base": "", "snapshot": False}
    Spider._cooldown = {}

    def _fail_first(self, url):
        return None if url.startswith("https://dead.") else raw
    Spider._http = _fail_first
    sp8 = Spider("https://dead.cn,https://alive.cn")
    h8 = sp8.homeContent(False)
    chk("死域名跳過取到數據", all(v["vod_id"] != DIAG_ID for v in h8["list"]))
    chk("成功域名被記住", Spider._cache["base"] == "https://alive.cn")
    chk("成功域名提到隊首", sp8._bases()[0] == "https://alive.cn")
    chk("封面用成功域名", h8["list"][0]["vod_pic"].startswith("https://alive.cn/"))

    # --- 結構契約
    chk("homeContent 有 class", set(["class", "filters", "list"]) <= set(h8))
    chk("categoryContent 有 pagecount", set(["page", "pagecount", "limit", "total", "list"]) <= set(c1))
    chk("playerContent 有 parse/url/header",
        set(["parse", "url", "header", "format"]) <= set(p))
    chk("vod 必備字段", set(["vod_id", "vod_name", "vod_pic", "vod_remarks"]) <= set(h8["list"][0]))

    # 收尾：恢復真實網絡方法
    Spider._http = _REAL_HTTP
    Spider._cache = {"data": None, "ts": 0.0, "base": "", "snapshot": False}
    Spider._cooldown = {}
    print("全部 %d 項本地斷言通過" % ok[0])


_REAL_HTTP = Spider._http

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a.strip()]
    try:
        if "--check" in args:
            _selftest()
        elif "--offline" in args:
            _run_offline()
        else:
            _run_online()
    except SystemExit:
        raise
    except Exception as exc:                      # 命令列不吞棧
        print("運行失敗：%s: %s" % (type(exc).__name__, exc))
        sys.exit(2)
