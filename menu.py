#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Author: omi
# @Date:   2014-08-24 21:51:57
"""
网易云音乐 Menu
"""
from __future__ import print_function, unicode_literals, division, absolute_import

import time
# import curses
import threading
import sys
import os
import signal
import webbrowser
import locale
import hashlib
from collections import namedtuple

from future.builtins import range, str

from api import NetEase
from player import Player
# from ui import Ui
# from osdlyrics import show_lyrics_new_process
from config import Config
from utils import notify
from storage import Storage
from cache import Cache
import logger


locale.setlocale(locale.LC_ALL, "")

log = logger.getLogger(__name__)


def carousel(left, right, x):
    # carousel x in [left, right]
    if x > right:
        return left
    elif x < left:
        return right
    else:
        return x


shortcut = [
    ["j", "Down      ", "下移"],
    ["k", "Up        ", "上移"],
    ["h", "Back      ", "后退"],
    ["l", "Forward   ", "前进"],
    ["u", "Prev page ", "上一页"],
    ["d", "Next page ", "下一页"],
    ["f", "Search    ", "快速搜索"],
    ["[", "Prev song ", "上一曲"],
    ["]", "Next song ", "下一曲"],
    [" ", "Play/Pause", "播放/暂停"],
    ["?", "Shuffle          ", "手气不错"],
    ["=", "Volume+          ", "音量增加"],
    ["-", "Volume-          ", "音量减少"],
    ["m", "Menu             ", "主菜单"],
    ["p", "Present/History  ", "当前/历史播放列表"],
    ["i", "Music Info       ", "当前音乐信息"],
    ["Shift+p", "Playing Mode     ", "播放模式切换"],
    ["Shift+a", "Enter album      ", "进入专辑"],
    ["a", "Add              ", "添加曲目到打碟"],
    ["z", "DJ list          ", "打碟列表（退出后清空）"],
    ["s", "Star      ", "添加到本地收藏"],
    ["c", "Collection", "本地收藏列表"],
    ["r", "Remove    ", "删除当前条目"],
    ["Shift+j", "Move Down ", "向下移动当前条目"],
    ["Shift+k", "Move Up   ", "向上移动当前条目"],
    [",", "Like      ", "喜爱"],
    ["Shfit+c", "Cache     ", "缓存歌曲到本地"],
    [".", "Trash FM  ", "删除 FM"],
    ["/", "Next FM   ", "下一 FM"],
    ["q", "Quit      ", "退出"],
    ["w", "Quit&Clear", "退出并清除用户信息"],
]


class Menu(object):
    def __init__(self):
        self.config = Config()
        self.datatype = "main"
        self.title = "网易云音乐"
        self.datalist = [
            "排行榜",
            "艺术家",
            "新碟上架",
            "精选歌单",
            "我的歌单",
            "主播电台",
            "每日推荐歌曲",
            "每日推荐歌单",
            "私人FM",
            "搜索",
            "帮助",
        ]
        self.offset = 0
        self.index = 0
        self.storage = Storage()
        self.storage.load()
        self.collection = self.storage.database["collections"]
        self.player = Player()
        self.player.playing_song_changed_callback = self.song_changed_callback
        self.cache = Cache()
        # self.ui = Ui()
        self.api = NetEase()
        # self.screen = curses.initscr()
        # self.screen.keypad(1)
        self.step = 10
        self.stack = []
        self.djstack = []
        self.at_playing_list = False
        self.enter_flag = True
        signal.signal(signal.SIGWINCH, self.change_term)
        signal.signal(signal.SIGINT, self.send_kill)
        self.menu_starts = time.time()
        self.countdown_start = time.time()
        self.countdown = -1
        self.is_in_countdown = False

    @property
    def user(self):
        return self.storage.database["user"]

    @property
    def account(self):
        return self.user["username"]

    @property
    def md5pass(self):
        return self.user["password"]

    @property
    def userid(self):
        return self.user["user_id"]

    @property
    def username(self):
        return self.user["nickname"]

    def login(self):
        if self.account and self.md5pass:
            account, md5pass = self.account, self.md5pass
        else:
            #modified
            account = str(input('name:'))
            password = str(input('password:'))
            md5pass = hashlib.md5(password.encode("utf-8")).hexdigest()

        resp = self.api.login(account, md5pass)
        if resp["code"] == 200:
            userid = resp["account"]["id"]
            nickname = resp["profile"]["nickname"]
            self.storage.login(account, md5pass, userid, nickname)
            print('that is right........')
            return True
        else:
            self.storage.logout()
            # x = self.ui.build_login_error()
            # if x != ord("1"):
            #     return False
            return self.login()

    def search(self, category):
        # self.ui.screen.timeout(-1)
        SearchArg = namedtuple("SearchArg", ["prompt", "api_type", "post_process"])
        category_map = {
            "songs": SearchArg("搜索歌曲：", 1, lambda datalist: datalist),
            "albums": SearchArg("搜索专辑：", 10, lambda datalist: datalist),
            "artists": SearchArg("搜索艺术家：", 100, lambda datalist: datalist),
            "playlists": SearchArg("搜索网易精选集：", 1000, lambda datalist: datalist),
        }

        prompt, api_type, post_process = category_map[category]
        # keyword = self.ui.get_param(prompt)
        keyword = str(input('Input the song\'s name:'))

        if not keyword:
            return []

        data = self.api.search(keyword, api_type)
        if not data:
            return data

        datalist = post_process(data.get(category, []))
        return self.api.dig_info(datalist, category)

    def change_term(self, signum, frame):
        self.ui.screen.clear()
        self.ui.screen.refresh()

    def send_kill(self, signum, fram):
        self.player.stop()
        self.cache.quit()
        self.storage.save()
        # curses.endwin()
        sys.exit()

    def update_alert(self, version):
        latest = Menu().check_version()
        if latest != version and latest != 0:
            notify("MusicBox Update is available", 1)
            time.sleep(0.5)
            notify(
                "NetEase-MusicBox installed version:"
                + version
                + "\nNetEase-MusicBox latest version:"
                + latest,
                0,
            )

    def check_version(self):
        # 检查更新 && 签到
        try:
            mobile = self.api.daily_task(is_mobile=True)
            pc = self.api.daily_task(is_mobile=False)

            if mobile["code"] == 200:
                notify("移动端签到成功", 1)
            if pc["code"] == 200:
                notify("PC端签到成功", 1)

            data = self.api.get_version()
            return data["info"]["version"]
        except KeyError as e:
            return 0

    def start_fork(self, version):
        pid = os.fork()
        if pid == 0:
            Menu().update_alert(version)
        else:
            Menu().start()

    def play_pause(self):
        if self.player.is_empty:
            return
        if not self.player.playing_flag:
            self.player.resume()
        else:
            self.player.pause()

    def next_song(self):
        if self.player.is_empty:
            return
        self.player.next()

    def previous_song(self):
        if self.player.is_empty:
            return
        self.player.prev()

    def start(self):

        # while True:

        #     print('input 1:login,2:search,100:break')
        #     num = int(input('Please input your choice:'))   
        #     print('you input {}'.format(num))

        #     if (num == 1):
        #         print('username before: {}'.format(self.user))
        #         myplaylist = self.request_api(self.api.user_playlist, self.userid)
        #         print(myplaylist)
        #         print('username: {}'.format(self.user))
        #     elif num == 2:
        #         datalist = self.search('songs')
        #         print('search result:')
        #         for idxx,val in enumerate(datalist):
        #             print('{}:{}-{}'.format(idxx,val['song_name'],val['artist']))
        #             if idxx > 10:
        #                 break;

        #     elif num == 100:
        #         break

        #############################################################afer:

        def print_info():
            print('----------------------------')
            print('1:清空信息并退出')
            print('2:上移')
            print('3:下移')
            print('4:搜索')
            print('5:播放')
            print('6:登录')
            print('7:个人歌单')
            print('100:直接退出')
            print('----------------------------')



        while True:
            datatype = self.datatype
            title = self.title
            datalist = self.datalist
            offset = self.offset
            idx = self.index
            step = self.step

            print_info()

            key = int(input('请输入你的选择:'))



            if key == 100:
                print('正在退出....')
                self.player.stop()
                self.storage.save()
                break

            elif key == 1:
                self.api.logout()
                print('正在退出....')
                self.player.stop()
                break

            elif key == 2:
                if idx == offset:
                    if offset == 0:
                        continue
                    self.offset -= step
                    # 移动光标到最后一列
                    self.index = offset - 1
                else:
                    self.index = carousel(
                        offset, min(len(datalist), offset + step) - 1, idx - 1
                    )
                self.menu_starts = time.time()
            elif key == 3:
                if idx == min(len(datalist), offset + step) - 1:
                    if offset + step >= len(datalist):
                        continue
                    self.offset += step
                    # 移动光标到第一列
                    self.index = offset + step
                else:
                    self.index = carousel(
                        offset, min(len(datalist), offset + step) - 1, idx + 1
                    )
                self.menu_starts = time.time()
            elif key == 4:
                self.index = 0
                self.offset = 0
                idx = 1;
                SearchCategory = namedtuple("SearchCategory", ["type", "title"])
                idx_map = {
                    0: SearchCategory("playlists", "精选歌单搜索列表"),
                    1: SearchCategory("songs", "歌曲搜索列表"),
                    2: SearchCategory("artists", "艺术家搜索列表"),
                    3: SearchCategory("albums", "专辑搜索列表"),
                }
                self.datatype, self.title = idx_map[idx]
                self.datalist = self.search(self.datatype)
                

                print('search result:')
                for idxx,val in enumerate(self.datalist):
                    print('{}:{}-{}'.format(idxx,val['song_name'],val['artist']))
                    if idxx > 10:
                        break;

                which_one = int(input('输入想要播放的序号：'))

                while which_one > 10 or which_one < 0:
                    which_one = int(input('序号不合理,重新输入：'))

                self.player.new_player_list('songs',self.title,self.datalist,-1)
                self.idx = which_one
                self.player.play_or_pause(self.idx,self.at_playing_list)


            elif key == 5:
                print('当前的歌单：')
                cnt = 0
                for key in self.player.songs.keys():
                    print('{}.{}----{}'.format(cnt,self.player.songs[key]['song_name'],self.player.songs[key]['artist']))
                    cnt += 1
                    if cnt > 10:
                        break
                
                which_one = int(input('输入想要播放的序号：'))
                while which_one > 10 or which_one < 0:
                    which_one = int(input('序号不合理,重新输入：'))
                self.idx = which_one
                self.player.play_or_pause(self.idx,self.at_playing_list)
            elif key == 6:
                myplaylist = self.request_api(self.api.user_playlist, self.userid)
                self.datatype = 'top_playlists'
                myplaylist = self.api.dig_info(myplaylist, self.datatype)
                notify('登录成功')
            elif key == 7:
                myplaylist = self.request_api(self.api.user_playlist, self.userid)
                self.datatype = 'top_playlists'
                myplaylist = self.api.dig_info(myplaylist, self.datatype)
                print('{}的歌单:'.format(self.username))
                for x,y in enumerate(myplaylist):
                    print('{}.{}'.format(x,y['playlist_name']))
                


                

    def dispatch_enter(self, idx):
        # The end of stack
        netease = self.api
        datatype = self.datatype
        title = self.title
        datalist = self.datalist
        offset = self.offset
        index = self.index
        self.stack.append([datatype, title, datalist, offset, index])

        if idx >= len(self.datalist):
            return False

        if datatype == "main":
            self.choice_channel(idx)

        # 该艺术家的热门歌曲
        elif datatype == "artists":
            artist_name = datalist[idx]["artists_name"]
            artist_id = datalist[idx]["artist_id"]

            self.datatype = "artist_info"
            self.title += " > " + artist_name
            self.datalist = [
                {"item": "{}的热门歌曲".format(artist_name), "id": artist_id},
                {"item": "{}的所有专辑".format(artist_name), "id": artist_id},
            ]

        elif datatype == "artist_info":
            self.title += " > " + datalist[idx]["item"]
            artist_id = datalist[0]["id"]
            if idx == 0:
                self.datatype = "songs"
                songs = netease.artists(artist_id)
                self.datalist = netease.dig_info(songs, "songs")

            elif idx == 1:
                albums = netease.get_artist_album(artist_id)
                self.datatype = "albums"
                self.datalist = netease.dig_info(albums, "albums")

        elif datatype == "djchannels":
            radio_id = datalist[idx]["id"]
            programs = netease.djprograms(radio_id)
            self.title += " > " + datalist[idx]["name"]
            self.datatype = "songs"
            self.datalist = netease.dig_info(programs, "songs")

        # 该专辑包含的歌曲
        elif datatype == "albums":
            album_id = datalist[idx]["album_id"]
            songs = netease.album(album_id)
            self.datatype = "songs"
            self.datalist = netease.dig_info(songs, "songs")
            self.title += " > " + datalist[idx]["albums_name"]

        # 精选歌单选项
        elif datatype == "recommend_lists":
            data = self.datalist[idx]
            self.datatype = data["datatype"]
            self.datalist = netease.dig_info(data["callback"](), self.datatype)
            self.title += " > " + data["title"]

        # 全站置顶歌单包含的歌曲
        elif datatype in ["top_playlists", "playlists"]:
            playlist_id = datalist[idx]["playlist_id"]
            songs = netease.playlist_detail(playlist_id)
            self.datatype = "songs"
            self.datalist = netease.dig_info(songs, "songs")
            self.title += " > " + datalist[idx]["playlist_name"]

        # 分类精选
        elif datatype == "playlist_classes":
            # 分类名称
            data = self.datalist[idx]
            self.datatype = "playlist_class_detail"
            self.datalist = netease.dig_info(data, self.datatype)
            self.title += " > " + data

        # 某一分类的详情
        elif datatype == "playlist_class_detail":
            # 子类别
            data = self.datalist[idx]
            self.datatype = "top_playlists"
            log.error(data)
            self.datalist = netease.dig_info(netease.top_playlists(data), self.datatype)
            self.title += " > " + data

        # 歌曲评论
        elif datatype in ["songs", "fmsongs"]:
            song_id = datalist[idx]["song_id"]
            comments = self.api.song_comments(song_id, limit=100)
            try:
                hotcomments = comments["hotComments"]
                comcomments = comments["comments"]
            except KeyError:
                hotcomments = comcomments = []
            self.datalist = []
            for one_comment in hotcomments:
                self.datalist.append(
                    "(热评 %s❤️ ️)%s:%s"
                    % (
                        one_comment["likedCount"],
                        one_comment["user"]["nickname"],
                        one_comment["content"],
                    )
                )
            for one_comment in comcomments:
                self.datalist.append(one_comment["content"])
            self.datatype = "comments"
            self.title = "网易云音乐 > 评论:%s" % datalist[idx]["song_name"]
            self.offset = 0
            self.index = 0

        # 歌曲榜单
        elif datatype == "toplists":
            songs = netease.top_songlist(idx)
            self.title += " > " + self.datalist[idx]
            self.datalist = netease.dig_info(songs, "songs")
            self.datatype = "songs"

        # 搜索菜单
        elif datatype == "search":
            self.index = 0
            self.offset = 0
            SearchCategory = namedtuple("SearchCategory", ["type", "title"])
            idx_map = {
                0: SearchCategory("playlists", "精选歌单搜索列表"),
                1: SearchCategory("songs", "歌曲搜索列表"),
                2: SearchCategory("artists", "艺术家搜索列表"),
                3: SearchCategory("albums", "专辑搜索列表"),
            }
            self.datatype, self.title = idx_map[idx]
            self.datalist = self.search(self.datatype)
        else:
            self.enter_flag = False

    def show_playing_song(self):
        if self.player.is_empty:
            return

        if not self.at_playing_list:
            self.stack.append(
                [self.datatype, self.title, self.datalist, self.offset, self.index]
            )
            self.at_playing_list = True

        self.datatype = self.player.info["player_list_type"]
        self.title = self.player.info["player_list_title"]
        self.datalist = [self.player.songs[i] for i in self.player.info["player_list"]]
        self.index = self.player.info["idx"]
        self.offset = self.index // self.step * self.step

    def song_changed_callback(self):
        if self.at_playing_list:
            self.show_playing_song()

    def fm_callback(self):
        # log.debug('FM CallBack.')
        data = self.get_new_fm()
        self.player.append_songs(data)
        if self.datatype == "fmsongs":
            if self.player.is_empty:
                return
            self.datatype = self.player.info["player_list_type"]
            self.title = self.player.info["player_list_title"]
            self.datalist = []
            for i in self.player.info["player_list"]:
                self.datalist.append(self.player.songs[i])
            self.index = self.player.info["idx"]
            self.offset = self.index // self.step * self.step
            if not self.player.playing_flag:
                switch_flag = False
                self.player.play_or_pause(self.index, switch_flag)

    def request_api(self, func, *args):
        result = func(*args)
        if result:
            return result
        if not self.login():
            print('you really need to login')
            notify("You need to log in")
            return False
        return func(*args)

    def get_new_fm(self):
        data = self.request_api(self.api.personal_fm)
        if not data:
            return []
        return self.api.dig_info(data, "fmsongs")

    def choice_channel(self, idx):
        self.offset = 0
        self.index = 0

        if idx == 0:
            self.datalist = self.api.toplists
            self.title += " > 排行榜"
            self.datatype = "toplists"
        elif idx == 1:
            artists = self.api.top_artists()
            self.datalist = self.api.dig_info(artists, "artists")
            self.title += " > 艺术家"
            self.datatype = "artists"
        elif idx == 2:
            albums = self.api.new_albums()
            self.datalist = self.api.dig_info(albums, "albums")
            self.title += " > 新碟上架"
            self.datatype = "albums"
        elif idx == 3:
            self.datalist = [
                {
                    "title": "全站置顶",
                    "datatype": "top_playlists",
                    "callback": self.api.top_playlists,
                },
                {
                    "title": "分类精选",
                    "datatype": "playlist_classes",
                    "callback": lambda: [],
                },
            ]
            self.title += " > 精选歌单"
            self.datatype = "recommend_lists"
        elif idx == 4:
            myplaylist = self.request_api(self.api.user_playlist, self.userid)
            self.datatype = "top_playlists"
            self.datalist = self.api.dig_info(myplaylist, self.datatype)
            self.title += " > " + self.username + " 的歌单"
        elif idx == 5:
            self.datatype = "djchannels"
            self.title += " > 主播电台"
            self.datalist = self.api.djchannels()
        elif idx == 6:
            self.datatype = "songs"
            self.title += " > 每日推荐歌曲"
            myplaylist = self.request_api(self.api.recommend_playlist)
            if myplaylist == -1:
                return
            self.datalist = self.api.dig_info(myplaylist, self.datatype)
        elif idx == 7:
            myplaylist = self.request_api(self.api.recommend_resource)
            self.datatype = "top_playlists"
            self.title += " > 每日推荐歌单"
            self.datalist = self.api.dig_info(myplaylist, self.datatype)
        elif idx == 8:
            self.datatype = "fmsongs"
            self.title += " > 私人FM"
            self.datalist = self.get_new_fm()
        elif idx == 9:
            self.datatype = "search"
            self.title += " > 搜索"
            self.datalist = ["歌曲", "艺术家", "专辑", "网易精选集"]
        elif idx == 10:
            self.datatype = "help"
            self.title += " > 帮助"
            self.datalist = shortcut
