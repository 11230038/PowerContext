"""Seed lore cards for the Cat Tavern.

Each card is a small piece of world knowledge. The backend retrieves cards
from seekdb for the current player input and hands the text to the Dify LLM
node, so the tavern stays consistent across sessions and players.
"""

from __future__ import annotations

LORE_CARDS: list[dict[str, object]] = [
    {
        "card_id": "LORE-FISH",
        "title": "鱼干失窃案",
        "content": "吧台后面有一只陶罐，里面原本有七条风干小鱼。老白坚称自己一条都没吃，但每次盘点都会少一条。窗边那只乌鸦总在案发时出现，老白却从来不肯怀疑它。",
        "tags": "鱼干 偷吃 乌鸦 吧台 失窃",
        "weight": 10,
    },
    {
        "card_id": "LORE-CAT",
        "title": "老白的九条命",
        "content": "老白是猫酒馆的掌柜，一只毛色发灰的黑猫。它说自己九条命只剩三条，最恨客人提“狗”这个字。提一次，酒钱翻倍；提两次，会被请去后巷吹风。",
        "tags": "老白 猫 掌柜 狗 规矩",
        "weight": 10,
    },
    {
        "card_id": "LORE-LEDGER",
        "title": "会顶嘴的账本",
        "content": "柜台上那本牛皮账本会自己写字。赊账超过三天，它就在页脚用毛笔写脏话；超过七天，它会开始编造你根本没点过的酒。",
        "tags": "账本 赊账 钱 利息 柜台",
        "weight": 8,
    },
    {
        "card_id": "LORE-WELL",
        "title": "后巷的月光井",
        "content": "后巷有一口井，月圆时井底会出现第二个月亮。把秘密说给井听，第二天会变成一杯味道很怪但很贵的酒。老白收三成。",
        "tags": "后巷 月光 井 秘密 酒",
        "weight": 8,
    },
    {
        "card_id": "LORE-BELL",
        "title": "猫王的旧铃铛",
        "content": "门楣上挂着一只生锈的铃铛，据说是猫王留下的。铃铛一响，店里所有猫必须暂停撒谎三秒。老白每次都会在这三秒里打喷嚏。",
        "tags": "铃铛 猫王 门楣 撒谎 规矩",
        "weight": 7,
    },
    {
        "card_id": "LORE-PIANO",
        "title": "地窖里的钢琴",
        "content": "地窖有一架只有老鼠会弹的钢琴。弹对曲子，楼上会下一场小雨；弹错一个音，整条街都会起雾。老鼠们说这是工会福利。",
        "tags": "地窖 钢琴 老鼠 下雨 雾",
        "weight": 7,
    },
    {
        "card_id": "LORE-CUP",
        "title": "会涨潮的酒杯",
        "content": "店里的酒杯能分辨谎言。客人说谎时，杯里的酒面会慢慢涨高。老白从不提醒，只会在涨到杯沿时递上一张昂贵的干布。",
        "tags": "酒杯 说谎 涨潮 干布 酒",
        "weight": 7,
    },
    {
        "card_id": "LORE-UNION",
        "title": "老鼠工会",
        "content": "厨房地板下住着老鼠工会，它们用面包屑投票。工会罢工时厨房停火，老白只能给客人端上“空气炖汤”，并坚称这是本店特色。",
        "tags": "老鼠 工会 厨房 面包 罢工",
        "weight": 6,
    },
    {
        "card_id": "LORE-CARD",
        "title": "打烊后的牌局",
        "content": "每天打烊后，老白会和三位看不见的客人打牌。输的人要讲一个从未对任何人说过的秘密。老白已经输了四十七次，但没人听过它讲秘密。",
        "tags": "牌局 打烊 秘密 客人 打牌",
        "weight": 6,
    },
    {
        "card_id": "LORE-DOOR",
        "title": "不存在的后门",
        "content": "酒馆后墙上有一扇门，平时摸不到。只有承认自己迷路的人，才能把门推开。门后是什么，取决于推门的人有多想回家。",
        "tags": "后门 迷路 门 回家 后墙",
        "weight": 6,
    },
    {
        "card_id": "LORE-SALT",
        "title": "盐罐里的耳朵",
        "content": "每张桌子上都有一只盐罐，盐里埋着一只小耳朵。客人说话时它会偷听，被听走的秘密会让盐变甜。老白用甜盐做招牌菜。",
        "tags": "盐 耳朵 偷听 秘密 甜",
        "weight": 5,
    },
    {
        "card_id": "LORE-UMBRELLA",
        "title": "借伞要还一场雨",
        "content": "门口的木桶里插着几把旧伞，谁都可以借。规矩是必须在晴天还一场雨：把伞撑开，站在太阳底下，直到有人问你为什么。",
        "tags": "伞 雨 借 晴天 规矩",
        "weight": 5,
    },
    {
        "card_id": "LORE-POSTER",
        "title": "失踪的寻猫启事",
        "content": "墙上贴着一张发黄的寻猫启事，照片里的猫和老白年轻时一模一样。启事背面写着一行小字：“别找了，它现在过得很好。”",
        "tags": "寻猫 启事 照片 老白 失踪",
        "weight": 5,
    },
    {
        "card_id": "LORE-JUKEBOX",
        "title": "只会唱反调的点歌机",
        "content": "角落里的点歌机永远唱反调：点情歌它放哀乐，点哀乐它放摇篮曲，点《生日快乐》它会沉默很久，然后放一段猫叫。",
        "tags": "点歌 音乐 反调 情歌 猫叫",
        "weight": 4,
    },
    {
        "card_id": "LORE-STOOL",
        "title": "第三条凳子",
        "content": "吧台前第三条凳子会让人说真心话。坐上去的人会突然开始解释自己为什么半夜不回家。老白说那张凳子从来没被人坐过，但凳面很热。",
        "tags": "凳子 真心话 吧台 半夜 回家",
        "weight": 4,
    },
    {
        "card_id": "LORE-TIP",
        "title": "小费罐里的牙",
        "content": "柜台角落有一只小费罐，里面除了硬币还有一颗乳牙。投一枚硬币进去，罐子会用很小很小的声音告诉你一个别人的秘密。",
        "tags": "小费 硬币 牙 秘密 柜台",
        "weight": 4,
    },
]
