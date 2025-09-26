import requests
from lxml import etree
import re
from urllib.parse import urljoin
import os

import asyncio
import aiohttp
import aiofiles

from Crypto.Cipher import AES  # pip install pycryptodome

headers = {
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 "
                      "Safari/537.36 ",
    }



def get_iframe_src(url):
    resp = requests.get(url, headers=headers)
    tree = etree.HTML(resp.text)
    src = tree.xpath("//iframe/@src")[0]
    return src

def get_m3u8_url(url):
    resp = requests.get(url, headers=headers)
    obj = re.compile(r'url："(?P<m3u8>.*?)"', re.S)
    m3u8 = obj.search(resp.text).group("m3u8")
    return m3u8

def download_m3u8(url):
    resp = requests.get(url, headers=headers)
    with open("first.m3u8", mode="w", encoding="utf-8") as f:
        f.write(resp.text)
    # 这个位置不要边读边写，注意缩进
    with open("first.m3u8", mode="r", encoding="utf-8") as f2:
        for line in f2:
            if line.startwith("#"):
                continue
            # 此时的Line就是第二层m3u8的地址
            line = line.strip()  # 注意文件里看不见的换行，要去掉，否则会有意想不到的错误
            line = urljoin(url, line)  # 拼接网址

            # 下载第二层m3u8
            resp = requests.get(line, headers=headers)
            with open("second.m3u8", mode='w', encoding='utf-8') as f3:
                f3.write(resp.text)
                break  # 可加，可不加

async def download_one(url, sem):
    async with sem:  # 使用信号量控制访问频率
        file_name = url.split("/")[-1]
        file_path = './解密前/'+file_name
        print(file_name, "开始工作了!")
        flag = True
        for i in range(10):  # 重试的最高次数为10次
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, headers=headers) as resp:
                        content = await resp.content.read()
                        # 写入文件
                        async with aiofiles.open(file_path, mode="wb") as f:
                            await f.write(content)
                print(file_name, "下载完成!")
                flag = False
                break
            except Exception as e:
                print(file_name, "出错了，马上重试", e)  # 给个提示，看到错误提示
        if flag:
            f = open("xxxx.log", mode='a', encoding='utf-8')
            f.write(url)
            f.write('\n')

async def download_all_videos():
    # 信号量, 用来控制协程并发量
    sem = asyncio.Semaphore(100)  # 网吧电影中极个别电影需要控制在5左右
    # 1.读取文件
    tasks = []
    with open("second.m3u8", mode='r', encoding='utf-8') as f:
        for line in f:
            if line.startwith("#"):
                continue
            line = line.strip()  # 此时line就是下载地址
            # 2.创建任务
            t = asyncio.create_task(download_one(line, sem))
            tasks.append(t)
    # 3.统一等待
    await asyncio.wait(tasks)

def get_key():
    with open("second.m3u8", mode='r', encoding='utf-8') as f:
        file_content = f.read()  # 读取到所有内容
        obj = re.compile(r'URI="(?P<key_url>.*?)"')
        key_url = obj.search(file_content).group("key_url")
        resp = requests.get(key_url, headers=headers)  # 发请求，拿秘钥
        return resp.content  # 直接拿字节，为了解密的时候，直接丢进去就可以了。因为解密包需要的是字节

# 解密的协程逻辑
# 读M3U8文件，拿到文件名称和路径
# 每个ts文件一个任务
# 在每个任务中，解密即可

async def desc_one(file_path, key):
    file_name = file_path.split("/")[-1]
    new_file_path = "./解密后/"+file_name
    # 解密
    async with aiofiles.open(file_path, mode="rb") as f1,\
            aiofiles.open(new_file_path, mode="wb") as f2:
        content = await f1.read()
        # 解密
        # 固定逻辑，创建一个加密器
        aes = AES.new(key=key, mode=AES.MODE_CBC, IV=b"0000000000000000")  # 常用加密模式mode = MODE_CBC,MODE_ECB , 查看这个new函数源代码，不难发现有的模式需要用到可选参数 IV="" ，IV这个在m3u8文件里可能会有提示，如果没有，可以尝试用16个0试试
        new_content = aes.decrypt(content)  # 解密，补充：aes.encrypt() 是加密
        await f2.write(new_content)  # 写入新文件
    print(new_file_path, "解密成功!")

async def desc_all(key):
    tasks = []
    with open("second.m3u8", mode="r", encoding='utf-8') as f:
        for line in f:
            if line.startswith("#"):
                continue
            line = line.strip()
            file_name = line.split("/")[-1]
            file_path = './解密前/' + file_name
            # 创建任务，去解密
            t = asyncio.create_task(desc_one(file_path, key))
            tasks.append(t)
    await asyncio.wait(tasks)

def merge():
    # 视频片段合成
    # B站视频，不适用这个
    # 需要一个命令，不同系统用不同命令
    # windows：copy /b a.ts+b.ts+c.ts xxx.mp4
    # linux/mac：cat a.ts b.ts c.ts > xxx.mp4
    # 共同的坑：
    # 1.执行命令 太长了不行，需要分段合并
    # 2.执行命令的时候，容易出现乱码，采用popen来执行命令，就可以避免乱码
    # 3.你只需要关注，是否合并成功了
    # os.system("dir")  # 直接给命令 会有乱码
    # r = os.popen("dir")  # popen不会主动打印，需要另外打印
    # print(r.read())  # 可以暂时性的避免乱码

    # 分段合并
    # 合并，要考虑顺序
    file_list = []
    with open("second.m3u8", mode="r", encoding='utf-8') as f:
        for line in f:
            if line.startswith("#"):
                continue
            line = line.strip()
            file_name = line.split('/')[-1]
            file_list.append(file_name)

    # 进入到文件夹内
    os.chdir("./解密后")  # 更换工作目录

    # file_list 所有文件名称
    temp = []  # [a.ts, b.ts, c.ts]
    n = 1
    for i in range(len(file_list)):
        # 每 20 个合并一次
        file_name = file_list[i]
        temp.append(file_name)
        if i != 0 and i % 20 == 0:
            # 可以合并一次
            cmd = f"copy /b {'+'.join(temp)} {n}.ts"
            r = os.popen(cmd)
            print(r.read())
            temp = []  # 新列表
            n = n + 1
    # 需要把剩余的ts进行合并
    cmd = f"copy /b {'+'.join(temp)} {n}.ts"
    r = os.popen(cmd)
    print(r.read())
    n = n + 1
    # 第二次大合并  1.ts + 2.ts + 3.ts xxx.mp4
    last_temp = []
    for i in range(1, n):
        last_temp.append(f"{i}.ts")
    # 第二次大合并的结尾大合并
    cmd = f"copy /b {'+'.join(last_temp)} xxx.mp4"
    r = os.popen(cmd)
    print(r.read())

    # 回来
    # os.chdir("../")  # ../ 表示上层文件夹

def main():
    url = ""
    # 1.拿到iframe的src属性值
    src = get_iframe_src(url)
    print(src)
    # 2.发送请求到iframe的src路径，获取到M3U8地址
    src = urljoin(url, src)
    m3u8_url = get_m3u8_url(src)
    # 3.下载m3u8文件
    download_m3u8(m3u8_url)
    # 4.下载视频
    # event_loop = asyncio.get_event_loop()
    # event_loop.run_until_complete(download_all_videos())
    asyncio.run(download_all_videos())
    # 5.拿秘钥
    key = get_key()
    # 6.解密
    asyncio.run(desc_all(key))
    print("全部完成")
    # 7.合成
    merge()

if __name__ == '__main__':
    main()













