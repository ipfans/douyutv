#!/usr/bin/env python
# coding=utf-8
"""Douyu Helper with python3 and asyncio."""

import asyncio
import hashlib
import json
import re
import sys
import threading
import time
import urllib
import uuid

import requests


# yapf: disable
ua = "Mozilla/5.0 (Windows NT 6.3; Win64; x64) AppleWebKit/537.36 (KHTML, " + \
     "like Gecko) Chrome/41.0.2272.118 Safari/537.36"
# yapf: enable


class DouyuTV(object):
    """DouyuTV class is for asyncio fetch douyu bullet screen."""

    def __init__(self, roomid, loop):
        super(DouyuTV, self).__init__()
        self.islive = True
        self.roomid = roomid
        self.server = {
            'add': 'danmu.douyutv.com',
            'port': '12602',
            'gid': '1',
            'status': '0',
            'rid': str(roomid)}
        self.sock = None
        self.danmuStatus = True
        self.loop = loop
        self.r = None  # asyncio reader
        self.w = None  # asyncio writer

    def islive(self, islive):
        """set islive state."""
        self.islive = islive

    def status_fetch(self):
        hea = {'User-Agent': ua}
        url = 'http://www.douyutv.com/' + self.roomid
        html = requests.get(url, headers=hea).text
        status = re.search("ROOM = ([^;]+);", html)
        if status:
            status = json.loads(status.group(1))
            self.server["status"] = status["show_status"]
            if status["show_status"] == 1:
                self.server["rid"] = status["room_id"]
                print("正在访问: " + status["room_name"])
                room_config = re.search("room_args = ([^;]+);", html)
                if room_config:
                    room_config = json.loads(
                        urllib.parse.unquote(
                            json.loads(room_config.group(1))["server_config"]))
                    self.server["ip"] = room_config[2]["ip"]
                    self.server["port"] = room_config[2]["port"]
                else:
                    print("读取房间服务器配置错误")
                    self.server['status'] = 2
            else:
                print('该主播没有直播')
                self.server['status'] = 2
        else:
            print('页面查询错误，请检查ID是否正确。')
            self.server['status'] = 2

    def context_parser(self, context):
        contextList = context.split(b'\x00"')[0].split(b'\xb2\x02')
        for cl in contextList:
            cl = cl.decode('utf-8', '.ignore')
            if re.search('msgrepeaterlist', cl):
                self.server['add'] = re.findall('Sip@AA=(.*?)@', cl)
                self.server['dport'] = re.findall('Sport@AA=(\d+)', cl)
            elif re.search('setmsggroup', cl):
                self.server['gid'] = re.findall('gid@=(\d+)/', cl)
                self.server['rid'] = re.findall('rid@=(.*?)/', cl)

    def sendmsg(self, msgstr):
        # print("called sendmsg")
        msg = msgstr.encode('utf-8')
        data_length = len(msg) + 8
        code = 689
        # yapf: disable
        msgHead = int.to_bytes(data_length, 4, 'little') + \
            int.to_bytes(data_length, 4, 'little') + \
            int.to_bytes(code, 4, 'little')
        # yapf: enable
        self.w.write(msgHead)
        # print("msg header sent.")
        self.w.write(msg)
        # print("sendmsg end.")

    async def dynamic_get(self):
        self.r, self.w = await asyncio.open_connection(
            self.server.get('ip'),
            int(self.server.get('port')),
            loop=self.loop)
        if self.r is None or self.w is None:
            print("创建服务器连接错误")
            return
        devid = uuid.uuid1().hex.swapcase()
        rt = str(int(time.time()))
        hashvk = hashlib.md5()
        vk = rt + '7oE9nPEG9xXV69phU31FYCLUagKeYtsF' + devid
        hashvk.update(vk.encode('utf-8'))
        vk = hashvk.hexdigest()
        username = ''
        password = ''
        rid = self.server.get('rid')
        # yapf: disable
        msg = 'type@=loginreq' + '/username@=' + username + '/ct@=0' + \
              '/password@=' + password + '/roomid@=' + str(rid) + \
              '/devid@=' + devid + '/rt@=' + rt + '/vk@=' + vk + \
              '/ver@=20150929' + '/\x00'
        # yapf: enable
        # print("loginreq sending...")
        self.sendmsg(msg)
        # print("loginreq end.")
        context = await self.r.read(1024)
        context = context.split(b'\xb2\x02')[1].decode('utf-8')
        typeID1st = re.findall('type@=(.*?)/', context)[0]
        if typeID1st != 'error':
            self.sendmsg(msg)
            context = await self.r.read(1024)
            self.context_parser(context)
            print('group ID get:', self.server['gid'])
        else:
            self.server['gid'] = '-1'
        self.w.close()

    async def keeplive(self):
        while self.islive:
            print('===keepalive===')
            msg = 'type@=keeplive/tick@=' + str(int(time.time())) + '/\x00'
            self.sendmsg(msg)
            await asyncio.sleep(40)
        self.w.close()

    def keeplive_wrap(self):
        self.keeplive_thread = asyncio.run_coroutine_threadsafe(
            self.keeplive(), self.loop)

    async def danmu(self):
        while self.islive:
            context = await self.r.read(1024)
            chatmsgLst = context.split(b'\xb2\x02')
            for chatmsg in chatmsgLst[1:]:
                typeContent = re.search(b'type@=(.*?)/', chatmsg)
                if typeContent:
                    if typeContent.group(1) == b'chatmsg':
                        try:
                            content = b''.join(re.findall(
                                b'txt@=(.*?)/', chatmsg)).decode(
                                    'utf-8', "replace")
                            nick = b''.join(re.findall(
                                b'nn@=(.*?)@', chatmsg)).decode(
                                    'utf-8', "replace").replace("/txt", "")
                            print(nick + ':' + content)
                        except:
                            print('GBK encode error, perhaps special string')
                    elif typeContent.group(1) == b'keeplive':
                        pass

    async def process(self):
        self.r, self.w = await asyncio.open_connection(
            self.server["add"][0],
            int(self.server["dport"][0]),
            loop=self.loop)
        rid = ''.join(self.server.get('rid'))
        gid = ''.join(self.server.get('gid'))
        msg = 'type@=loginreq/username@=/password@=/roomid@=' + rid + '/\x00'
        self.sendmsg(msg)
        await self.r.read(1024)
        msg = 'type@=joingroup/rid@=' + rid + '/gid@=' + gid + '/\x00'
        self.sendmsg(msg)
        threading.Thread(target=self.keeplive_wrap).start()
        await self.danmu()
        self.w.close()

    async def show(self):
        self.status_fetch()
        if self.server['status'] == 2:
            return
        await self.dynamic_get()
        try:
            await self.process()
        except InterruptedError:
            print("ending...")
            self.keeplive_thread.cancel()
            while self.keeplive_thread.done() is False:
                await asyncio.sleep(3)
            self.islive = False


if __name__ == '__main__':
    uid = sys.argv[1] if len(sys.argv) > 1 else '71713'
    loop = asyncio.get_event_loop()
    douyu = DouyuTV(uid, loop)
    loop.run_until_complete(douyu.show())
