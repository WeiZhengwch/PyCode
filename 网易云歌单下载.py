import os
import re
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
import wx
import wx.xrc
from mutagen.mp3 import MP3  # 用于检测音频时长
from selenium import webdriver
from selenium.common import TimeoutException, StaleElementReferenceException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

chrome_options = Options()
chrome_options.add_argument("--headless")  # 如果已经加了，保持
chrome_options.add_argument("--disable-gpu")  # 如果已经加了，保持
chrome_options.add_argument("--no-sandbox")  # 在某些环境下有帮助，禁用沙盒
chrome_options.add_argument("--disable-dev-shm-usage")  # 解决某些环境中的内存限制问题
chrome_options.add_argument("start-maximized")  # 启动时最大化窗口
chrome_options.add_argument("disable-infobars")  # 禁止提示栏
chrome_options.add_argument("--remote-debugging-port=9222")  # 开启调试模式，可能有助于捕获错误

class MyFrame1(threading.Thread, wx.Frame):
    musicData = []
    MIN_DURATION = 60  # 最低要求60秒

    def __init__(self, threadID, name, counter):
        wx.Frame.__init__(self, None, id=wx.ID_ANY, title=u"网易云音乐歌单下载",
                          pos=wx.DefaultPosition, size=wx.Size(450, 500),
                          style=wx.DEFAULT_FRAME_STYLE | wx.TAB_TRAVERSAL)
        self.SetSizeHints(wx.DefaultSize, wx.DefaultSize)
        self.SetBackgroundColour(wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOW))

        # 布局设置
        bSizer4 = wx.BoxSizer(wx.VERTICAL)
        bSizer5 = wx.BoxSizer(wx.HORIZONTAL)

        self.m_staticText3 = wx.StaticText(self, wx.ID_ANY, u"歌单 URL", wx.DefaultPosition, wx.DefaultSize, 0)
        self.m_staticText3.Wrap(-1)
        self.m_staticText3.SetFont(
            wx.Font(13, wx.FONTFAMILY_DECORATIVE, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL, False, ""))
        bSizer5.Add(self.m_staticText3, 0, wx.ALL, 5)

        self.url_text = wx.TextCtrl(self, wx.ID_ANY, wx.EmptyString, wx.DefaultPosition, wx.Size(300, -1), 0)
        bSizer5.Add(self.url_text, 0, wx.ALL, 5)

        self.down_button = wx.Button(self, wx.ID_ANY, u"下载歌单", wx.DefaultPosition, wx.DefaultSize, 0)
        bSizer5.Add(self.down_button, 0, wx.ALL, 5)
        bSizer4.Add(bSizer5, 0, wx.EXPAND, 4)

        self.output_text = wx.TextCtrl(self, wx.ID_ANY,
                                       u"请在网页中复制歌单 URL\n例如：https://music.163.com/#/playlist?id=xxxxxxxxxx\n保存目录：d:/music\n-------------------------------------------------------\n",
                                       wx.DefaultPosition, wx.Size(430, 300), wx.TE_MULTILINE)
        bSizer4.Add(self.output_text, 1, wx.ALL | wx.EXPAND, 5)

        self.gauge = wx.Gauge(self, wx.ID_ANY, range=100, pos=wx.DefaultPosition, size=wx.Size(430, 25))
        bSizer4.Add(self.gauge, 0, wx.ALL | wx.EXPAND, 5)

        self.currently_downloading = wx.StaticText(self, wx.ID_ANY, u"正在下载：", wx.DefaultPosition, wx.Size(430, 25),
                                                   0)
        bSizer4.Add(self.currently_downloading, 0, wx.ALL | wx.EXPAND, 5)

        self.SetSizer(bSizer4)
        self.Layout()
        self.Centre(wx.BOTH)

        self.down_button.Bind(wx.EVT_BUTTON, self.main_button_click)

        # 初始化线程部分
        threading.Thread.__init__(self)
        self.threadID = threadID
        self.name = name
        self.counter = counter

        if not os.path.exists("d:/music"):
            os.mkdir('d:/music')

        # Cookie 管理等代码（可参照原改进版）
        self.cookie_file = "cookie.txt"
        self.cookie = self.load_cookie()
        if not self.cookie:
            dlg = wx.TextEntryDialog(self, "请输入Cookie", "Cookie")
            if dlg.ShowModal() == wx.ID_OK:
                self.cookie = dlg.GetValue()
                self.save_cookie(self.cookie)
            dlg.Destroy()

        self.lock = threading.Lock()
        self.downloading_songs = []
        self.dest_folder = None
        self.failed_songs = []

    def load_cookie(self):
        if os.path.exists(self.cookie_file):
            with open(self.cookie_file, "r", encoding="utf-8") as f:
                return f.read().strip()
        return ""

    def save_cookie(self, cookie_value):
        with open(self.cookie_file, "w", encoding="utf-8") as f:
            f.write(cookie_value)

    def main_button_click(self, event):
        # 创建以当前时间戳命名的文件夹，用于保存本次下载的歌单文件
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.dest_folder = os.path.join("d:/music", timestamp)
        if not os.path.exists(self.dest_folder):
            os.makedirs(self.dest_folder)
        self.musicData = self.getMusicData(self.url_text.GetValue().replace("#/", ""))
        if len(self.musicData) > 0:
            wx.CallAfter(self.gauge.SetRange, len(self.musicData))
            wx.CallAfter(self.gauge.SetValue, 0)
            self.start()

    def run(self):
        total = len(self.musicData)
        progress_value = 0
        with ThreadPoolExecutor(max_workers=4) as executor:
            future_to_song = {executor.submit(self.process_song, song): song for song in self.musicData}
            for future in as_completed(future_to_song):
                song = future_to_song[future]
                try:
                    result = future.result()
                    wx.CallAfter(self.output_text.AppendText, result + "\n")
                except Exception as exc:
                    wx.CallAfter(self.output_text.AppendText,
                                 "***** " + song['name'] + " 下载出错: " + str(exc) + "\n")
                progress_value += 1
                wx.CallAfter(self.gauge.SetValue, progress_value)
        # 所有任务结束后，列出下载失败的歌曲
        if self.failed_songs:
            failed_str = "下载失败的歌曲: " + ", ".join(self.failed_songs) + "\n"
            wx.CallAfter(self.output_text.AppendText, failed_str)
        wx.CallAfter(self.output_text.AppendText, "Download complete!\n")

    def process_song(self, song):
        song_name = re.sub(r"[\/\\\:\*\?\"\<\>\|]", "_", song['name'])
        dest_path = os.path.join(self.dest_folder, song_name + '.mp3')
        if os.path.exists(dest_path):
            return "***** " + song_name + " 已存在，跳过下载"
        with self.lock:
            self.downloading_songs.append(song['name'])
            wx.CallAfter(self.currently_downloading.SetLabel,
                         "正在下载：" + ", ".join(self.downloading_songs))
        try:
            original_url = 'http://music.163.com/song/media/outer/url?id=' + str(song['id']) + '.mp3'
            wx.CallAfter(self.output_text.AppendText, "尝试原版下载: " + song_name + "\n")
            if not self.saveFile(original_url, dest_path):
                wx.CallAfter(self.output_text.AppendText, "原版下载失败，准备使用改进版下载: " + song_name + "\n")
                if os.path.exists(dest_path):
                    os.remove(dest_path)
                raise Exception("原版下载失败")
            else:
                if not self.is_valid_audio_file(dest_path):
                    wx.CallAfter(self.output_text.AppendText,
                                 "原版下载文件时长不足，准备使用改进版下载: " + song_name + "\n")
                    os.remove(dest_path)
                    raise Exception("原版下载文件无效")
                else:
                    return "***** " + song_name + " 下载成功 (原版)"
        except Exception as e:
            try:
                result = self.download_with_improved_method(song, dest_path)
                return result
            except Exception as e_improved:
                # 如果首次改进版搜索未找到匹配，则尝试使用“歌名 - 歌手”方式再次搜索
                if "未找到匹配" in str(e_improved):
                    wx.CallAfter(self.output_text.AppendText, "使用备用查询方式下载: " + song_name + "\n")
                    try:
                        result = self.download_with_improved_method(song, dest_path,
                                                                    custom_query=f"{song['name']} - {song['artist']}")
                        return result
                    except Exception as e_alt:
                        # 记录下载失败的歌曲
                        with self.lock:
                            self.failed_songs.append(song['name'])
                        raise e_alt
                else:
                    with self.lock:
                        self.failed_songs.append(song['name'])
                    raise e_improved
        finally:
            with self.lock:
                if song['name'] in self.downloading_songs:
                    self.downloading_songs.remove(song['name'])
                    wx.CallAfter(self.currently_downloading.SetLabel,
                                 "正在下载：" + ", ".join(
                                     self.downloading_songs) if self.downloading_songs else "当前无任务")

    def download_with_improved_method(self, song, dest_path, retries=3, delay=0, max_pages=3, custom_query=None):
        # 使用 Selenium 获取高品质下载链接
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--disable-gpu")
        driver = webdriver.Chrome(options=chrome_options)

        attempt = 0
        found = False
        # 根据是否提供备用查询，确定搜索关键词
        query = custom_query if custom_query else f"{song['name']}"
        while attempt < retries and not found:
            try:
                attempt += 1
                print(f"尝试第 {attempt} 次下载 {song['name']} 使用查询: {query}")

                # 初始化页码
                current_page = 1
                while current_page <= max_pages:
                    search_url = "https://www.ihaoge.net/search/result?q=" + urllib.parse.quote(
                        query) + "&nsid=4" + f"&page={current_page}"
                    driver.get(search_url)
                    print(f"当前页: {current_page} 搜索链接: {search_url}")

                    result_elems = WebDriverWait(driver, 10).until(
                        EC.presence_of_all_elements_located((By.XPATH, "//a[contains(@href, '/tool/song/')]"))
                    )
                    results = []
                    for elem in result_elems:
                        try:
                            href = elem.get_attribute("href")
                            text = elem.text.strip()
                            results.append((href, text))
                        except Exception as e:
                            print(f"提取元素信息时出错: {e}")

                    try:
                        album_elem = WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.XPATH, "//span[contains(text(), '专辑名称：')]"))
                        )
                        album_name = album_elem.text.split("专辑名称：")[1].strip()
                    except (StaleElementReferenceException, TimeoutException):
                        album_name = None

                    for song_page_url, song_info in results:
                        driver.get(song_page_url)
                        if "–" in song_info:
                            track_name, artist_name = song_info.split("–", 1)
                            track_name = track_name.strip()
                            artist_name = artist_name.strip()
                            print(song['artist'].lower(), " ", artist_name.lower(), " ", album_name, " ",
                                  song.get('album', ''))
                            if song['artist'].lower() in artist_name.lower() or (
                                    album_name and album_name == song.get('album', '')):
                                high_quality_elem = WebDriverWait(driver, 5).until(
                                    EC.presence_of_element_located((By.XPATH, "//a[contains(text(), '高品质')]"))
                                )
                                download_url = high_quality_elem.get_attribute("href")
                                if download_url.startswith("/"):
                                    download_url = "https://www.ihaoge.net" + download_url
                                if not self.saveFile(download_url, dest_path):
                                    raise Exception("改进版下载失败多次")
                                if not self.is_valid_audio_file(dest_path):
                                    os.remove(dest_path)
                                    raise Exception("下载的文件无效")
                                found = True
                                driver.quit()
                                return "***** " + song['name'] + " 下载成功 (改进版)"
                    print(f"当前页 {current_page} 未找到匹配项，尝试下一页...")
                    current_page += 1
                raise Exception(f"未找到匹配歌手 {song['artist']} 的歌曲: {song['name']}")
            except Exception as e:
                print(f"尝试下载 {song['name']} 时出现错误: {e}")
                if attempt < retries:
                    print(f"等待 {delay} 秒后重试...")
                    time.sleep(delay)
                else:
                    driver.quit()
                    raise e

    def is_valid_audio_file(self, path):
        """
        使用 mutagen 检测下载的 MP3 时长是否大于或等于 MIN_DURATION（单位秒）。
        若无法解析则返回 False。
        """
        try:
            audio = MP3(path)
            if audio.info.length < self.MIN_DURATION:
                return False
            return True
        except Exception:
            return False

    def getMusicData(self, url):
        # 从URL中解析歌单ID，并调用网易云 API 获取歌单信息
        parsed = urllib.parse.urlparse(url)
        qs = urllib.parse.parse_qs(parsed.query)
        playlist_id = qs.get("id", [None])[0]
        if not playlist_id:
            self.output_text.AppendText("无法解析歌单ID\n")
            return []
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Cookie': self.cookie,
            'Referer': 'https://music.163.com/'
        }
        api_url = "https://music.163.com/api/playlist/detail?id=" + playlist_id
        retries = 3
        data = None
        while retries > 0:
            response = requests.get(api_url, headers=headers)
            data = response.json()
            if data.get("code") == -447:
                self.output_text.AppendText("服务器忙碌，请稍后再试！重试中...\n")
                retries -= 1
                time.sleep(2)
            else:
                break
        if not data or "result" not in data:
            self.output_text.AppendText("API 返回错误: " + str(data) + "\n")
            return []
        tracks = data["result"].get("tracks", [])
        # 针对特殊情况，比如返回歌曲数为10，提示 Cookie 问题
        if len(tracks) == 10:
            self.output_text.AppendText("检测到返回歌曲数为10，可能 cookie 无效，请输入新的 cookie\n")
            dlg = wx.TextEntryDialog(self, "请输入新的 cookie", "Cookie")
            if dlg.ShowModal() == wx.ID_OK:
                new_cookie = dlg.GetValue()
                self.cookie = new_cookie
                self.save_cookie(new_cookie)
            dlg.Destroy()
            return self.getMusicData(url)
        tempArr = []
        for track in tracks:
            track_id = track["id"]
            track_name = track["name"]
            track_album = track['album'].get('name')
            artists = track.get("ar") or track.get("artists", [])
            artist_name = artists[0]["name"] if artists and "name" in artists[0] else ""
            tempArr.append({'id': track_id, 'name': track_name, 'artist': artist_name, 'album': track_album})
        return tempArr

    def saveFile(self, url, path, retries=3, delay=2):
        for attempt in range(1, retries + 1):
            try:
                response = requests.get(url, timeout=10)
                if response.status_code == 200:
                    total_length = response.headers.get('content-length')
                    if total_length is None:
                        with open(path, 'wb') as f:
                            f.write(response.content)
                    else:
                        total_length = int(total_length)
                        with open(path, 'wb') as f:
                            downloaded = 0
                            for chunk in response.iter_content(chunk_size=1024):
                                if chunk:
                                    f.write(chunk)
                                    downloaded += len(chunk)
                    return True
                else:
                    raise Exception("HTTP 状态码: " + str(response.status_code))
            except Exception as e:
                print(f"下载尝试 {attempt} 失败: {e}")
                time.sleep(delay)
        return False


def main():
    app = wx.App(False)
    frame = MyFrame1(1, "Thread-1", 1)
    frame.Show(True)
    app.MainLoop()


if __name__ == '__main__':
    main()
