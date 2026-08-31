# 下载清单

<!--
────────────────────────────────────────────────────────────────
怎么用

  1. 复制这个文件，改成你自己的清单，比如  日语课.md
  2. 先检查清单写得对不对（不会下载，很快）：
         ./vd batch 日语课.md --dry-run
  3. 确认无误再真正下载：
         ./vd batch 日语课.md
  4. 想顺便抽帧（每 5 秒一帧）：
         ./vd batch 日语课.md --frames 5

────────────────────────────────────────────────────────────────
怎么写

  每行一条，下面几种写法都认，可以在同一个文件里混着用：

      - [视频名称](链接)          ← 推荐
      | 视频名称 | 链接 |          ← Markdown 表格
      视频名称 | 链接
      链接                        ← 不写名称，就用课程自带的标题

  链接直接从浏览器地址栏复制，**不用管里面的 product_id**，工具会自己处理。

  文件名：
    · 不用加 .mp4 后缀
    · 名字里有 / : ? * 这类字符也没关系，会自动替换掉
    · 想让文件排序整齐，就自己在名字前面加 01 02 03
    · 名字重复时会自动加 (2) (3)，不会覆盖已有文件

  会被忽略的内容：
    · ## 章节标题（只是给你自己看的分组，不影响下载）
    · 空行、这段注释、``` 代码块
    · 已经下载过的视频会自动跳过，可以放心重复跑

────────────────────────────────────────────────────────────────
下面是示例，删掉换成你自己的
-->

## 第1讲 形容词

- [01 形容词的分类](https://appxxxxxxxxxxx.pc.xiaoe-tech.com/p/t_pc/course_pc_detail/video/v_xxxxxxxxxxxxxxxxxxxxxxxx?product_id=course_xxxxxxxxxxxxxxxxxxxxxxxxxx)
- [02 4种基本形式](https://appxxxxxxxxxxx.pc.xiaoe-tech.com/p/t_pc/course_pc_detail/video/v_yyyyyyyyyyyyyyyyyyyyyyyy?product_id=course_xxxxxxxxxxxxxxxxxxxxxxxxxx)

## 第2讲 XXX

<!-- 表格写法，效果完全一样，看你习惯 -->

| 视频名称 | 链接 |
| --- | --- |
| 03 XXXXXX | 把链接粘到这里 |
| 04 XXXXXX | 把链接粘到这里 |
