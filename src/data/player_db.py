"""
NBA 全联盟球员数据库
==================
按 30 支球队组织，每个球员包含：姓名、球队、位置、球衣号、新秀年、球星等级。

球星等级 (Tier) 决定 Base 卡基础价格区间：
  Tier 0 — MVP/超巨    ($80-200, 如 LeBron, Curry, Jokic, Wemby)
  Tier 1 — 全明星      ($30-70, 如 Edwards, Brunson, Sabonis)
  Tier 2 — 优质先发     ($10-25, 如 Jarrett Allen, Mikal Bridges)
  Tier 3 — 轮换球员     ($3-10, 如 Payton Pritchard, Naz Reid)
  Tier 4 — 板凳末端     ($1-3, 如 第11-15人)
  Tier 5 — 双向/底薪    ($0.50-1.50, 如 训练营合同)

总计 ~480 名球员，覆盖 NBA 30 支球队的 2024-25 赛季阵容。

数据来源参考: Basketball Reference, ESPN Depth Charts (2025年初)
"""

# ============================================================
# 球星等级 → 基础价格映射（用于模拟数据生成）
# ============================================================
TIER_PRICE_RANGE = {
    0: (80.0, 200.0),    # MVP/超巨
    1: (30.0, 70.0),     # 全明星
    2: (10.0, 25.0),     # 优质先发
    3: (3.0, 10.0),      # 轮换球员
    4: (1.0, 3.0),       # 板凳末端
    5: (0.50, 1.50),     # 双向/底薪
}

TIER_LABELS = {
    0: "MVP/超巨",
    1: "全明星",
    2: "优质先发",
    3: "轮换球员",
    4: "板凳末端",
    5: "双向/底薪",
}

# ============================================================
# 全联盟球员数据
# 格式: (姓名, 球衣号, 新秀年, Tier, 位置)
# ============================================================
# 注：部分球员去掉了变音符以便于 ASCII 兼容

NBA_TEAMS = {
    # ================================================================
    # 东部联盟 Eastern Conference
    # ================================================================

    "Atlanta Hawks": [
        ("Trae Young",          11, 2018, 1, "PG"),
        ("Jalen Johnson",        1, 2021, 2, "PF"),
        ("Dyson Daniels",       11, 2022, 2, "SG"),
        ("Onyeka Okongwu",      17, 2020, 2, "C"),
        ("Zaccharie Risacher",  10, 2024, 3, "SF"),
        ("Bogdan Bogdanovic",   13, 2014, 2, "SG"),
        ("Clint Capela",        15, 2014, 2, "C"),
        ("De'Andre Hunter",     12, 2019, 2, "SF"),
        ("Terance Mann",        14, 2019, 3, "SG"),
        ("Kobe Bufkin",          4, 2023, 3, "PG"),
        ("Garrison Mathews",    25, 2019, 3, "SG"),
        ("Mouhamed Gueye",      18, 2023, 4, "PF"),
        ("Vit Krejci",          27, 2021, 4, "SF"),
        ("David Roddy",         21, 2022, 4, "SF"),
        ("Dominick Barlow",     26, 2022, 5, "PF"),
    ],

    "Boston Celtics": [
        ("Jayson Tatum",         0, 2017, 0, "SF"),
        ("Jaylen Brown",         7, 2016, 1, "SG"),
        ("Kristaps Porzingis",   8, 2015, 1, "C"),
        ("Jrue Holiday",         4, 2009, 1, "PG"),
        ("Derrick White",        9, 2017, 1, "SG"),
        ("Payton Pritchard",    11, 2020, 3, "PG"),
        ("Al Horford",          42, 2007, 2, "C"),
        ("Sam Hauser",          30, 2021, 3, "SF"),
        ("Luke Kornet",         40, 2017, 3, "C"),
        ("Xavier Tillman",      26, 2020, 3, "PF"),
        ("Baylor Scheierman",   55, 2024, 4, "SG"),
        ("Jordan Walsh",        27, 2023, 4, "SF"),
        ("Neemias Queta",       88, 2021, 4, "C"),
        ("JD Davison",          20, 2022, 5, "PG"),
        ("Drew Peterson",       13, 2023, 5, "SF"),
    ],

    "Brooklyn Nets": [
        ("Cameron Johnson",      2, 2019, 2, "SF"),
        ("Nic Claxton",         33, 2019, 2, "C"),
        ("Cam Thomas",          24, 2021, 2, "SG"),
        ("D'Angelo Russell",     1, 2015, 2, "PG"),
        ("Noah Clowney",        21, 2023, 3, "PF"),
        ("Ziaire Williams",      8, 2021, 3, "SF"),
        ("Day'Ron Sharpe",      20, 2021, 3, "C"),
        ("Keon Johnson",        45, 2021, 3, "SG"),
        ("Jalen Wilson",        22, 2023, 3, "SF"),
        ("Trendon Watford",      9, 2021, 3, "PF"),
        ("Dariq Whitehead",      0, 2023, 4, "SG"),
        ("Tyrese Martin",       13, 2022, 4, "SG"),
        ("Tosan Evbuomwan",     10, 2023, 4, "SF"),
        ("Maxwell Lewis",       16, 2023, 5, "SF"),
        ("Reece Beekman",       14, 2024, 5, "PG"),
    ],

    "Charlotte Hornets": [
        ("LaMelo Ball",          1, 2020, 1, "PG"),
        ("Brandon Miller",      24, 2023, 1, "SF"),
        ("Miles Bridges",        0, 2018, 2, "PF"),
        ("Mark Williams",        5, 2022, 2, "C"),
        ("Nick Smith Jr.",       8, 2023, 3, "PG"),
        ("Grant Williams",       2, 2019, 3, "PF"),
        ("Josh Green",          10, 2020, 3, "SG"),
        ("Tidjane Salaun",      31, 2024, 3, "PF"),
        ("Cody Martin",         11, 2019, 3, "SF"),
        ("Seth Curry",          30, 2013, 3, "SG"),
        ("Moussa Diabate",      18, 2022, 4, "C"),
        ("DaQuan Jeffries",      3, 2019, 4, "SG"),
        ("KJ Simpson",          25, 2024, 4, "PG"),
        ("Jusuf Nurkic",        20, 2014, 3, "C"),
        ("Taj Gibson",          67, 2009, 4, "PF"),
    ],

    "Chicago Bulls": [
        ("Zach LaVine",          8, 2014, 1, "SG"),
        ("Nikola Vucevic",       9, 2011, 2, "C"),
        ("Coby White",           0, 2019, 2, "PG"),
        ("Josh Giddey",          3, 2021, 2, "PG"),
        ("Ayo Dosunmu",         12, 2021, 3, "SG"),
        ("Patrick Williams",    44, 2020, 3, "PF"),
        ("Matas Buzelis",       14, 2024, 3, "SF"),
        ("Lonzo Ball",           2, 2017, 3, "PG"),
        ("Jalen Smith",         25, 2020, 3, "C"),
        ("Kevin Huerter",       13, 2018, 3, "SG"),
        ("Dalen Terry",         25, 2022, 4, "SF"),
        ("Julian Phillips",     15, 2023, 4, "SF"),
        ("Tre Jones",            5, 2020, 4, "PG"),
        ("Zach Collins",        19, 2017, 4, "C"),
        ("Jevon Carter",         5, 2018, 4, "PG"),
    ],

    "Cleveland Cavaliers": [
        ("Donovan Mitchell",    45, 2017, 0, "SG"),
        ("Darius Garland",      10, 2019, 1, "PG"),
        ("Evan Mobley",          4, 2021, 1, "PF"),
        ("Jarrett Allen",       31, 2017, 2, "C"),
        ("Max Strus",            1, 2019, 3, "SG"),
        ("De'Andre Hunter",     12, 2019, 2, "SF"),
        ("Ty Jerome",            2, 2019, 3, "PG"),
        ("Isaac Okoro",         35, 2020, 3, "SF"),
        ("Sam Merrill",          5, 2020, 3, "SG"),
        ("Dean Wade",           32, 2019, 3, "PF"),
        ("Jaylon Tyson",        24, 2024, 4, "SG"),
        ("Craig Porter Jr.",     9, 2023, 4, "PG"),
        ("Tristan Thompson",    13, 2011, 4, "C"),
        ("Emoni Bates",         21, 2023, 5, "SF"),
        ("Nae'Qwan Tomlin",     15, 2024, 5, "PF"),
    ],

    "Detroit Pistons": [
        ("Cade Cunningham",      2, 2021, 1, "PG"),
        ("Jaden Ivey",          23, 2022, 2, "SG"),
        ("Jalen Duren",          0, 2022, 2, "C"),
        ("Ausar Thompson",       9, 2023, 2, "SF"),
        ("Tobias Harris",       12, 2011, 2, "PF"),
        ("Isaiah Stewart",      28, 2020, 3, "C"),
        ("Malik Beasley",        5, 2016, 3, "SG"),
        ("Ron Holland II",       0, 2024, 3, "SF"),
        ("Tim Hardaway Jr.",    11, 2013, 3, "SG"),
        ("Marcus Sasser",       25, 2023, 3, "PG"),
        ("Simone Fontecchio",   19, 2017, 4, "SF"),
        ("Paul Reed",            7, 2020, 4, "C"),
        ("Bobi Klintman",       34, 2024, 4, "PF"),
        ("Lindy Waters III",    12, 2021, 5, "SG"),
        ("Daniss Jenkins",       0, 2024, 5, "PG"),
    ],

    "Indiana Pacers": [
        ("Tyrese Haliburton",    0, 2020, 1, "PG"),
        ("Pascal Siakam",       43, 2016, 1, "PF"),
        ("Myles Turner",         33, 2015, 2, "C"),
        ("Bennedict Mathurin",   0, 2022, 2, "SG"),
        ("Andrew Nembhard",      2, 2022, 2, "PG"),
        ("Aaron Nesmith",       23, 2020, 3, "SF"),
        ("T.J. McConnell",       9, 2015, 3, "PG"),
        ("Obi Toppin",           1, 2020, 3, "PF"),
        ("Jarace Walker",        5, 2023, 3, "PF"),
        ("Thomas Bryant",       13, 2017, 3, "C"),
        ("Ben Sheppard",        26, 2023, 4, "SG"),
        ("Johnny Furphy",       12, 2024, 4, "SF"),
        ("James Johnson",       16, 2009, 4, "PF"),
        ("Quenton Jackson",     29, 2022, 5, "PG"),
        ("Enrique Freeman",      8, 2024, 5, "PF"),
    ],

    "Miami Heat": [
        ("Bam Adebayo",         13, 2017, 1, "C"),
        ("Tyler Herro",         14, 2019, 2, "SG"),
        ("Andrew Wiggins",      22, 2014, 2, "SF"),
        ("Terry Rozier",         2, 2015, 2, "PG"),
        ("Kel'el Ware",          1, 2024, 3, "C"),
        ("Jaime Jaquez Jr.",    24, 2023, 3, "SF"),
        ("Nikola Jovic",         5, 2022, 3, "PF"),
        ("Duncan Robinson",     55, 2018, 3, "SG"),
        ("Davion Mitchell",     45, 2021, 3, "PG"),
        ("Haywood Highsmith",   24, 2018, 4, "PF"),
        ("Alec Burks",          18, 2011, 4, "SG"),
        ("Kyle Anderson",        1, 2014, 4, "PF"),
        ("Pelle Larsson",        9, 2024, 4, "SG"),
        ("Keshad Johnson",      16, 2024, 5, "SF"),
        ("Josh Christopher",     8, 2021, 5, "SG"),
    ],

    "Milwaukee Bucks": [
        ("Giannis Antetokounmpo", 34, 2013, 0, "PF"),
        ("Damian Lillard",       0, 2012, 0, "PG"),
        ("Brook Lopez",         11, 2008, 2, "C"),
        ("Khris Middleton",     22, 2012, 2, "SF"),
        ("Bobby Portis",         9, 2015, 2, "PF"),
        ("Gary Trent Jr.",       5, 2018, 3, "SG"),
        ("Taurean Prince",      12, 2016, 3, "SF"),
        ("AJ Green",            20, 2022, 3, "SG"),
        ("Ryan Rollins",        13, 2022, 3, "PG"),
        ("Andre Jackson Jr.",   44, 2023, 4, "SG"),
        ("Kevin Porter Jr.",     3, 2019, 4, "SG"),
        ("Pat Connaughton",     24, 2015, 4, "SF"),
        ("Jericho Sims",         2, 2021, 4, "C"),
        ("Tyler Smith",         15, 2024, 5, "PF"),
        ("Chris Livingston",     7, 2023, 5, "SF"),
    ],

    "New York Knicks": [
        ("Jalen Brunson",       11, 2018, 0, "PG"),
        ("Karl-Anthony Towns",  32, 2015, 1, "C"),
        ("Mikal Bridges",        1, 2018, 1, "SF"),
        ("OG Anunoby",           8, 2017, 1, "SF"),
        ("Josh Hart",            3, 2017, 2, "SG"),
        ("Mitchell Robinson",   23, 2018, 2, "C"),
        ("Miles McBride",        2, 2021, 3, "PG"),
        ("Precious Achiuwa",     5, 2020, 3, "PF"),
        ("Cameron Payne",       15, 2015, 4, "PG"),
        ("Landry Shamet",       20, 2018, 4, "SG"),
        ("Ariel Hukporti",      55, 2024, 4, "C"),
        ("Tyler Kolek",         13, 2024, 4, "PG"),
        ("Pacome Dadiet",        4, 2024, 5, "SF"),
        ("Kevin McCullar Jr.",   9, 2024, 5, "SG"),
        ("Jacob Toppin",         0, 2023, 5, "SF"),
    ],

    "Orlando Magic": [
        ("Paolo Banchero",       5, 2022, 1, "PF"),
        ("Franz Wagner",        22, 2021, 1, "SF"),
        ("Jalen Suggs",          4, 2021, 2, "SG"),
        ("Wendell Carter Jr.",  34, 2018, 2, "C"),
        ("Kentavious Caldwell-Pope", 3, 2013, 2, "SG"),
        ("Cole Anthony",        50, 2020, 3, "PG"),
        ("Anthony Black",        0, 2023, 3, "PG"),
        ("Goga Bitadze",        35, 2019, 3, "C"),
        ("Jonathan Isaac",       1, 2017, 3, "PF"),
        ("Tristan da Silva",    23, 2024, 4, "SF"),
        ("Gary Harris",         14, 2014, 4, "SG"),
        ("Cory Joseph",          5, 2011, 4, "PG"),
        ("Moritz Wagner",       21, 2018, 4, "C"),
        ("Caleb Houstan",        2, 2022, 5, "SF"),
        ("Mac McClung",          0, 2021, 5, "PG"),
    ],

    "Philadelphia 76ers": [
        ("Joel Embiid",         21, 2014, 0, "C"),
        ("Tyrese Maxey",         0, 2020, 1, "PG"),
        ("Paul George",          8, 2010, 1, "SF"),
        ("Kelly Oubre Jr.",      9, 2015, 2, "SF"),
        ("Andre Drummond",       1, 2012, 3, "C"),
        ("Guerschon Yabusele",  28, 2016, 3, "PF"),
        ("Eric Gordon",         23, 2008, 3, "SG"),
        ("Kyle Lowry",           7, 2006, 3, "PG"),
        ("Jared McCain",        20, 2024, 3, "PG"),
        ("Ricky Council IV",    16, 2023, 4, "SG"),
        ("Adem Bona",           30, 2024, 4, "C"),
        ("Justin Edwards",      19, 2024, 4, "SF"),
        ("Quentin Grimes",       5, 2021, 4, "SG"),
        ("Chuma Okeke",         18, 2019, 5, "PF"),
        ("David Roddy",         21, 2022, 5, "SF"),
    ],

    "Toronto Raptors": [
        ("Scottie Barnes",       4, 2021, 1, "SF"),
        ("Immanuel Quickley",    5, 2020, 2, "PG"),
        ("RJ Barrett",           9, 2019, 2, "SG"),
        ("Gradey Dick",          1, 2023, 2, "SG"),
        ("Jakob Poeltl",        19, 2016, 2, "C"),
        ("Brandon Ingram",      14, 2016, 1, "SF"),
        ("Ochai Agbaji",        30, 2022, 3, "SG"),
        ("Chris Boucher",       25, 2017, 3, "PF"),
        ("Jamal Shead",         23, 2024, 3, "PG"),
        ("Jamison Battle",      22, 2024, 4, "SF"),
        ("Orlando Robinson",    10, 2022, 4, "C"),
        ("Jonathan Mogbo",       2, 2024, 4, "PF"),
        ("Garrett Temple",      17, 2009, 4, "SG"),
        ("AJ Lawson",            0, 2021, 5, "SG"),
        ("Jared Rhoden",         8, 2022, 5, "SF"),
    ],

    "Washington Wizards": [
        ("Jordan Poole",        13, 2019, 2, "SG"),
        ("Kyle Kuzma",          33, 2017, 2, "PF"),
        ("Alex Sarr",           20, 2024, 3, "C"),
        ("Bilal Coulibaly",      0, 2023, 3, "SF"),
        ("Bub Carrington",      17, 2024, 3, "PG"),
        ("Corey Kispert",       24, 2021, 3, "SF"),
        ("Malcolm Brogdon",     11, 2016, 3, "PG"),
        ("Kyshawn George",      18, 2024, 4, "SG"),
        ("Richaun Holmes",      22, 2015, 4, "C"),
        ("Justin Champagnie",    9, 2021, 4, "SF"),
        ("Saddiq Bey",          41, 2020, 4, "SF"),
        ("Anthony Gill",        16, 2016, 4, "PF"),
        ("Patrick Baldwin Jr.",  7, 2022, 5, "SF"),
        ("Jaylen Nowell",        4, 2019, 5, "SG"),
        ("Tristan Vukcevic",    35, 2023, 5, "C"),
    ],

    # ================================================================
    # 西部联盟 Western Conference
    # ================================================================

    "Denver Nuggets": [
        ("Nikola Jokic",        15, 2015, 0, "C"),
        ("Jamal Murray",        27, 2016, 1, "PG"),
        ("Michael Porter Jr.",   1, 2018, 2, "SF"),
        ("Aaron Gordon",        50, 2014, 2, "PF"),
        ("Christian Braun",      0, 2022, 3, "SG"),
        ("Russell Westbrook",    4, 2008, 2, "PG"),
        ("Peyton Watson",        8, 2022, 3, "SF"),
        ("Julian Strawther",     3, 2023, 4, "SG"),
        ("Zeke Nnaji",          22, 2020, 4, "PF"),
        ("Dario Saric",         20, 2014, 4, "C"),
        ("Vlatko Cancar",       31, 2017, 4, "PF"),
        ("Jalen Pickett",       24, 2023, 5, "PG"),
        ("Hunter Tyson",         5, 2023, 5, "SF"),
        ("DeAndre Jordan",       6, 2008, 4, "C"),
        ("Spencer Jones",       21, 2024, 5, "SF"),
    ],

    "Minnesota Timberwolves": [
        ("Anthony Edwards",      5, 2020, 1, "SG"),
        ("Julius Randle",       30, 2014, 2, "PF"),
        ("Rudy Gobert",         27, 2013, 2, "C"),
        ("Jaden McDaniels",      3, 2020, 2, "SF"),
        ("Naz Reid",            11, 2019, 3, "C"),
        ("Mike Conley",         10, 2007, 2, "PG"),
        ("Donte DiVincenzo",     0, 2018, 3, "SG"),
        ("Nickeil Alexander-Walker", 9, 2019, 3, "SG"),
        ("Rob Dillingham",       4, 2024, 3, "PG"),
        ("Terrence Shannon Jr.", 0, 2024, 4, "SG"),
        ("Josh Minott",          8, 2022, 4, "SF"),
        ("Luka Garza",          55, 2021, 4, "C"),
        ("Joe Ingles",           7, 2009, 4, "SF"),
        ("Leonard Miller",      33, 2023, 5, "PF"),
        ("Jaylen Clark",         0, 2023, 5, "SG"),
    ],

    "Oklahoma City Thunder": [
        ("Shai Gilgeous-Alexander", 2, 2018, 0, "PG"),
        ("Chet Holmgren",        7, 2022, 1, "C"),
        ("Jalen Williams",       8, 2022, 1, "SF"),
        ("Luguentz Dort",        5, 2019, 2, "SG"),
        ("Isaiah Hartenstein",  55, 2017, 2, "C"),
        ("Alex Caruso",          6, 2016, 3, "PG"),
        ("Cason Wallace",       22, 2023, 3, "PG"),
        ("Isaiah Joe",          11, 2020, 3, "SG"),
        ("Aaron Wiggins",       21, 2021, 3, "SF"),
        ("Jaylin Williams",      6, 2022, 3, "C"),
        ("Kenrich Williams",    34, 2018, 4, "PF"),
        ("Ousmane Dieng",       13, 2022, 4, "SF"),
        ("Dillon Jones",         3, 2024, 4, "PF"),
        ("Ajay Mitchell",       25, 2024, 5, "PG"),
        ("Branden Carlson",     15, 2024, 5, "C"),
    ],

    "Portland Trail Blazers": [
        ("Anfernee Simons",      1, 2018, 2, "SG"),
        ("Jerami Grant",         9, 2014, 2, "PF"),
        ("Scoot Henderson",      0, 2023, 2, "PG"),
        ("Shaedon Sharpe",      17, 2022, 2, "SG"),
        ("Deandre Ayton",        2, 2018, 2, "C"),
        ("Deni Avdija",          8, 2020, 3, "SF"),
        ("Donovan Clingan",     23, 2024, 3, "C"),
        ("Toumani Camara",      33, 2023, 3, "PF"),
        ("Robert Williams III", 35, 2018, 3, "C"),
        ("Matisse Thybulle",     4, 2019, 4, "SG"),
        ("Kris Murray",          8, 2023, 4, "SF"),
        ("Jabari Walker",        7, 2022, 4, "PF"),
        ("Rayan Rupert",        21, 2023, 5, "SG"),
        ("Duop Reath",          26, 2022, 5, "C"),
        ("Dalano Banton",       17, 2021, 5, "PG"),
    ],

    "Utah Jazz": [
        ("Lauri Markkanen",     23, 2017, 1, "PF"),
        ("John Collins",        20, 2017, 2, "C"),
        ("Collin Sexton",        2, 2018, 2, "PG"),
        ("Walker Kessler",      24, 2022, 2, "C"),
        ("Keyonte George",       3, 2023, 3, "SG"),
        ("Jordan Clarkson",      0, 2014, 3, "SG"),
        ("Brice Sensabaugh",    28, 2023, 3, "SF"),
        ("Isaiah Collier",      13, 2024, 3, "PG"),
        ("Kyle Filipowski",     22, 2024, 4, "C"),
        ("Cody Williams",        5, 2024, 4, "SF"),
        ("Taylor Hendricks",     0, 2023, 4, "PF"),
        ("Johnny Juzang",       33, 2022, 4, "SG"),
        ("Micah Potter",        25, 2021, 5, "C"),
        ("Svi Mykhailiuk",      19, 2018, 5, "SG"),
        ("Oscar Tshiebwe",      34, 2023, 5, "C"),
    ],

    "Golden State Warriors": [
        ("Stephen Curry",       30, 2009, 0, "PG"),
        ("Jimmy Butler",        10, 2011, 1, "SF"),
        ("Draymond Green",      23, 2012, 1, "PF"),
        ("Jonathan Kuminga",     0, 2021, 2, "PF"),
        ("Brandin Podziemski",   2, 2023, 2, "SG"),
        ("Buddy Hield",          7, 2016, 3, "SG"),
        ("Moses Moody",          4, 2021, 3, "SF"),
        ("Trayce Jackson-Davis", 32, 2023, 3, "C"),
        ("Kevon Looney",         5, 2015, 3, "C"),
        ("Gary Payton II",       0, 2016, 3, "SG"),
        ("Quinten Post",        21, 2024, 4, "C"),
        ("Gui Santos",          15, 2022, 4, "SF"),
        ("Pat Spencer",         61, 2024, 5, "PG"),
        ("Jackson Rowe",        44, 2024, 5, "SF"),
        ("Taran Armstrong",     12, 2024, 5, "PG"),
    ],

    "LA Clippers": [
        ("Kawhi Leonard",        2, 2011, 0, "SF"),
        ("James Harden",         1, 2009, 1, "PG"),
        ("Norman Powell",       24, 2015, 2, "SG"),
        ("Ivica Zubac",         40, 2016, 2, "C"),
        ("Bogdan Bogdanovic",   10, 2014, 2, "SG"),
        ("Kris Dunn",           14, 2016, 3, "PG"),
        ("Derrick Jones Jr.",   55, 2016, 3, "SF"),
        ("Nicolas Batum",       33, 2008, 3, "PF"),
        ("Amir Coffey",          7, 2019, 3, "SG"),
        ("Drew Eubanks",        15, 2018, 4, "C"),
        ("Ben Simmons",         25, 2016, 3, "PG"),
        ("Cam Christie",        12, 2024, 4, "SG"),
        ("Kobe Brown",          21, 2023, 5, "PF"),
        ("MarJon Beauchamp",     0, 2022, 5, "SF"),
        ("Trentyn Flowers",      9, 2024, 5, "SF"),
    ],

    "Los Angeles Lakers": [
        ("LeBron James",        23, 2003, 0, "SF"),
        ("Luka Doncic",         77, 2018, 0, "PG"),
        ("Austin Reaves",       15, 2021, 2, "SG"),
        ("Rui Hachimura",       28, 2019, 2, "PF"),
        ("Dorian Finney-Smith", 17, 2016, 3, "SF"),
        ("Jarred Vanderbilt",    2, 2018, 3, "PF"),
        ("Gabe Vincent",         7, 2018, 3, "PG"),
        ("Jaxson Hayes",        11, 2019, 3, "C"),
        ("Dalton Knecht",        4, 2024, 3, "SG"),
        ("Shake Milton",        20, 2018, 4, "PG"),
        ("Trey Jemison III",    55, 2023, 4, "C"),
        ("Bronny James",         9, 2024, 4, "SG"),
        ("Cam Reddish",          5, 2019, 4, "SF"),
        ("Maxi Kleber",         14, 2014, 4, "C"),
        ("Markieff Morris",     88, 2011, 5, "PF"),
    ],

    "Phoenix Suns": [
        ("Kevin Durant",        35, 2007, 0, "SF"),
        ("Devin Booker",         1, 2015, 1, "SG"),
        ("Bradley Beal",         3, 2012, 1, "SG"),
        ("Grayson Allen",        8, 2018, 3, "SG"),
        ("Nick Richards",        4, 2020, 3, "C"),
        ("Royce O'Neale",       00, 2015, 3, "PF"),
        ("Tyus Jones",          21, 2015, 3, "PG"),
        ("Bol Bol",             11, 2019, 3, "C"),
        ("Mason Plumlee",       22, 2013, 4, "C"),
        ("Ryan Dunn",            0, 2024, 4, "SF"),
        ("Oso Ighodaro",        12, 2024, 4, "C"),
        ("Monte Morris",        23, 2017, 4, "PG"),
        ("Collin Gillespie",    10, 2022, 5, "PG"),
        ("Jalen Bridges",       15, 2024, 5, "SF"),
        ("TyTy Washington Jr.", 14, 2022, 5, "PG"),
    ],

    "Sacramento Kings": [
        ("Domantas Sabonis",    11, 2016, 1, "C"),
        ("De'Aaron Fox",         5, 2017, 1, "PG"),
        ("DeMar DeRozan",       10, 2009, 1, "SF"),
        ("Malik Monk",           0, 2017, 2, "SG"),
        ("Keegan Murray",       13, 2022, 2, "PF"),
        ("Zach LaVine",          8, 2014, 1, "SG"),
        ("Keon Ellis",          23, 2022, 3, "SG"),
        ("Trey Lyles",          41, 2015, 3, "PF"),
        ("Jake LaRavia",         3, 2022, 3, "PF"),
        ("Devin Carter",        22, 2024, 4, "PG"),
        ("Jonas Valanciunas",   17, 2011, 3, "C"),
        ("Markelle Fultz",      20, 2017, 4, "PG"),
        ("Isaiah Crawford",     24, 2024, 5, "SF"),
        ("Terry Taylor",        32, 2021, 5, "PF"),
        ("Mason Jones",         15, 2020, 5, "SG"),
    ],

    "San Antonio Spurs": [
        ("Victor Wembanyama",    1, 2023, 0, "C"),
        ("De'Aaron Fox",         4, 2017, 1, "PG"),
        ("Stephon Castle",       5, 2024, 2, "PG"),
        ("Devin Vassell",       24, 2020, 2, "SG"),
        ("Jeremy Sochan",       10, 2022, 2, "PF"),
        ("Keldon Johnson",       0, 2019, 2, "SF"),
        ("Harrison Barnes",     40, 2012, 3, "SF"),
        ("Chris Paul",           3, 2005, 2, "PG"),
        ("Julian Champagnie",   30, 2022, 3, "SF"),
        ("Charles Bassey",      28, 2021, 4, "C"),
        ("Malaki Branham",      22, 2022, 4, "SG"),
        ("Blake Wesley",        14, 2022, 4, "PG"),
        ("Sandro Mamukelashvili", 54, 2021, 4, "C"),
        ("Harrison Ingram",     16, 2024, 5, "SF"),
        ("Riley Minix",         27, 2024, 5, "SF"),
    ],

    "Houston Rockets": [
        ("Jalen Green",          4, 2021, 2, "SG"),
        ("Alperen Sengun",      28, 2021, 1, "C"),
        ("Amen Thompson",        1, 2023, 2, "PG"),
        ("Fred VanVleet",       23, 2016, 2, "PG"),
        ("Dillon Brooks",        9, 2017, 2, "SF"),
        ("Jabari Smith Jr.",    10, 2022, 2, "PF"),
        ("Tari Eason",          17, 2022, 3, "PF"),
        ("Cam Whitmore",         7, 2023, 3, "SF"),
        ("Reed Sheppard",       15, 2024, 3, "PG"),
        ("Steven Adams",        12, 2013, 3, "C"),
        ("Jae'Sean Tate",        8, 2018, 4, "SF"),
        ("Aaron Holiday",        0, 2018, 4, "PG"),
        ("Jock Landale",         2, 2018, 4, "C"),
        ("Jeff Green",          32, 2007, 4, "PF"),
        ("Nate Williams",       19, 2022, 5, "SG"),
    ],

    "Dallas Mavericks": [
        ("Anthony Davis",        3, 2012, 0, "C"),
        ("Kyrie Irving",        11, 2011, 1, "PG"),
        ("Klay Thompson",       31, 2011, 1, "SG"),
        ("P.J. Washington",     25, 2019, 2, "PF"),
        ("Daniel Gafford",      21, 2019, 2, "C"),
        ("Dereck Lively II",     2, 2023, 2, "C"),
        ("Naji Marshall",       13, 2020, 3, "SF"),
        ("Spencer Dinwiddie",   26, 2014, 3, "PG"),
        ("Max Christie",        00, 2022, 3, "SG"),
        ("Caleb Martin",        16, 2019, 3, "SF"),
        ("Dwight Powell",        7, 2014, 4, "C"),
        ("Jaden Hardy",          1, 2022, 4, "SG"),
        ("Olivier-Maxence Prosper", 18, 2023, 4, "PF"),
        ("Kessler Edwards",     14, 2021, 5, "SF"),
        ("Brandon Williams",    10, 2021, 5, "PG"),
    ],

    "Memphis Grizzlies": [
        ("Ja Morant",           12, 2019, 1, "PG"),
        ("Jaren Jackson Jr.",   13, 2018, 1, "PF"),
        ("Desmond Bane",        22, 2020, 2, "SG"),
        ("Zach Edey",           14, 2024, 2, "C"),
        ("Santi Aldama",         7, 2021, 2, "PF"),
        ("Brandon Clarke",      15, 2019, 3, "PF"),
        ("Marcus Smart",        36, 2014, 3, "PG"),
        ("Luke Kennard",        10, 2017, 3, "SG"),
        ("Jaylen Wells",         0, 2024, 3, "SF"),
        ("Scotty Pippen Jr.",    1, 2022, 3, "PG"),
        ("Vince Williams Jr.",   5, 2022, 3, "SG"),
        ("GG Jackson",          45, 2023, 3, "PF"),
        ("John Konchar",        46, 2019, 4, "SG"),
        ("Jay Huff",            30, 2021, 4, "C"),
        ("Cam Spencer",         24, 2024, 5, "SG"),
    ],

    "New Orleans Pelicans": [
        ("Zion Williamson",      1, 2019, 1, "PF"),
        ("CJ McCollum",          3, 2013, 2, "PG"),
        ("Trey Murphy III",     25, 2021, 2, "SF"),
        ("Herbert Jones",        5, 2021, 2, "SF"),
        ("Dejounte Murray",      5, 2016, 2, "PG"),
        ("Yves Missi",          21, 2024, 3, "C"),
        ("Jordan Hawkins",      24, 2023, 3, "SG"),
        ("Jose Alvarado",       15, 2021, 3, "PG"),
        ("Bruce Brown",         11, 2018, 3, "SG"),
        ("Kelly Olynyk",        41, 2013, 3, "C"),
        ("Jeremiah Robinson-Earl", 50, 2021, 4, "PF"),
        ("Karlo Matkovic",      17, 2022, 4, "C"),
        ("Keion Brooks Jr.",     0, 2024, 5, "SF"),
        ("Brandon Boston Jr.",  12, 2021, 5, "SG"),
        ("Antonio Reeves",      14, 2024, 5, "SG"),
    ],
}

# ============================================================
# 退役球星库 (2026-08 新增)
# 结构同 NBA_TEAMS: 球队 -> [(name, jersey, rookie_year, tier, position)]
# 新秀年 = NBA 生涯首个赛季（关键：驱动表单"新秀资格自动校验"）
# ============================================================
RETIRED_PLAYERS = {
    "Los Angeles Lakers": [
        ("Kobe Bryant",             8, 1996, 0, "SG"),   # 1996-2016 湖人 20 年
        ("Magic Johnson",          32, 1979, 0, "PG"),   # 1979 新秀
        ("Shaquille O'Neal",       34, 1992, 0, "C"),    # 1992 新秀
        ("Kareem Abdul-Jabbar",    33, 1969, 0, "C"),    # 1969 新秀
        ("Jerry West",             44, 1960, 0, "SG"),   # 1960 新秀
        ("Wilt Chamberlain",       13, 1959, 0, "C"),    # 1959 新秀
    ],
    "Chicago Bulls": [
        ("Michael Jordan",         23, 1984, 0, "SG"),   # 1984 新秀
        ("Scottie Pippen",         33, 1987, 0, "SF"),   # 1987 新秀
        ("Derrick Rose",            1, 2008, 0, "PG"),   # 2008 新秀，2024 退役
        ("Dennis Rodman",          10, 1986, 2, "PF"),   # 1986 新秀
    ],
    "Boston Celtics": [
        ("Larry Bird",             33, 1979, 0, "SF"),   # 1979 新秀
        ("Bill Russell",            6, 1956, 0, "C"),    # 1956 新秀
        ("Paul Pierce",            34, 1998, 0, "SF"),   # 1998 新秀
        ("Kevin Garnett",           5, 1995, 0, "PF"),   # 1995 新秀
        ("Ray Allen",              20, 1996, 1, "SG"),   # 1996 新秀
        ("Robert Parish",          00, 1976, 1, "C"),    # 1976 新秀
        ("Rajon Rondo",             9, 2006, 2, "PG"),   # 2006 新秀，2024 退役
    ],
    "San Antonio Spurs": [
        ("Tim Duncan",             21, 1997, 0, "PF"),   # 1997 新秀
        ("David Robinson",         50, 1989, 1, "C"),    # 1989 新秀
        ("Tony Parker",             9, 2001, 1, "PG"),   # 2001 新秀
        ("Manu Ginobili",          20, 2002, 1, "SG"),   # 2002 新秀
    ],
    "Dallas Mavericks": [
        ("Dirk Nowitzki",          41, 1998, 0, "PF"),   # 1998 新秀
        ("Jason Kidd",              5, 1994, 0, "PG"),   # 1994 新秀
    ],
    "Miami Heat": [
        ("Dwyane Wade",             3, 2003, 0, "SG"),   # 2003 新秀
        ("Alonzo Mourning",        33, 1992, 1, "C"),    # 1992 新秀
        ("Chris Bosh",              1, 2003, 1, "PF"),   # 2003 新秀
    ],
    "Philadelphia 76ers": [
        ("Allen Iverson",           3, 1996, 0, "SG"),   # 1996 新秀
        ("Charles Barkley",        34, 1984, 0, "PF"),   # 1984 新秀
        ("Julius Erving",           6, 1971, 0, "SF"),   # 1971 (ABA)
        ("Moses Malone",            2, 1976, 1, "C"),    # 1976 (ABA)
    ],
    "Houston Rockets": [
        ("Hakeem Olajuwon",        34, 1984, 0, "C"),    # 1984 新秀
        ("Clyde Drexler",          22, 1983, 1, "SG"),   # 1983 新秀
        ("Yao Ming",               11, 2002, 1, "C"),    # 2002 新秀，姚明
    ],
    "New York Knicks": [
        ("Patrick Ewing",          33, 1985, 0, "C"),    # 1985 新秀
        ("Jeremy Lin",             17, 2010, 2, "PG"),   # 2010 新秀，林书豪
    ],
    "Detroit Pistons": [
        ("Isiah Thomas",           11, 1981, 1, "PG"),   # 1981 新秀
        ("Grant Hill",             33, 1994, 1, "SF"),   # 1994 新秀
    ],
    "Utah Jazz": [
        ("Karl Malone",            32, 1985, 0, "PF"),   # 1985 新秀
        ("John Stockton",          12, 1984, 1, "PG"),   # 1984 新秀
    ],
    "Oklahoma City Thunder": [
        ("Gary Payton",            20, 1990, 1, "PG"),   # 1990 新秀（超音速）
        ("Shawn Kemp",             40, 1989, 2, "PF"),   # 1989 新秀（超音速）
    ],
    "Orlando Magic": [
        ("Penny Hardaway",          1, 1993, 1, "PG"),   # 1993 新秀
    ],
    "Indiana Pacers": [
        ("Reggie Miller",          31, 1987, 1, "SG"),   # 1987 新秀
    ],
    "Toronto Raptors": [
        ("Vince Carter",           15, 1998, 1, "SG"),   # 1998 新秀
        ("Tracy McGrady",           1, 1997, 1, "SF"),   # 1997 新秀
    ],
    "Phoenix Suns": [
        ("Steve Nash",             13, 1996, 1, "PG"),   # 1996 新秀
    ],
    "Memphis Grizzlies": [
        ("Pau Gasol",              16, 2001, 1, "PF"),   # 2001 新秀
        ("Marc Gasol",             33, 2008, 1, "C"),    # 2008 新秀，2024 退役
    ],
    "Denver Nuggets": [
        ("Carmelo Anthony",        15, 2003, 0, "SF"),   # 2003 新秀，2023 退役
    ],
    "Los Angeles Clippers": [
        ("Blake Griffin",          23, 2009, 1, "PF"),   # 2009 新秀，2023 退役
    ],
    "Charlotte Hornets": [
        ("Kemba Walker",           15, 2011, 2, "PG"),   # 2011 新秀，2023 退役
    ],
    "Washington Wizards": [
        ("John Wall",               2, 2010, 1, "PG"),   # 2010 新秀，2023 退役
    ],
    "Golden State Warriors": [
        ("Chris Webber",            4, 1993, 1, "PF"),   # 1993 新秀
        ("Rick Barry",             24, 1965, 1, "SF"),   # 1965 新秀
    ],
    "Milwaukee Bucks": [
        ("易建联",                   9, 2007, 3, "PF"),   # 2007 新秀，Yi Jianlian
    ],
}

# 现役 + 退役合并字典（所有查询函数统一使用）
# 注意: 不能用 {**NBA_TEAMS, **RETIRED_PLAYERS} —— 同名球队键会被退役名单整体覆盖，
# 而是将退役球员追加到同名球队的现役名单之后（湖人 = 15 现役 + 6 退役 = 21 人）
_ALL_TEAMS = {team: list(players) for team, players in NBA_TEAMS.items()}
for _team, _players in RETIRED_PLAYERS.items():
    _ALL_TEAMS.setdefault(_team, []).extend(_players)


# ============================================================
# 便捷访问函数
# ============================================================

# 常见历史球星（不在现役名单中，卡淘标题常用中文名/英文名）
_HISTORIC_STARS = [
    "michael jordan", "jordan", "kobe bryant", "kobe", "shaquille o'neal", "shaq",
    "tim duncan", "kevin garnett", "dirk nowitzki", "dwyane wade", "allen iverson",
    "tracy mcgrady", "yao ming", "姚明", "易建联", "林书豪", "jeremy lin",
    "magic johnson", "larry bird", "bill russell", "wilt chamberlain",
    "kareem abdul", "scottie pippen", "paul pierce", "ray allen", "reggie miller",
    "grant hill", "steve nash", "jason kidd", "vince carter", "carmelo anthony",
    "derrick rose", "james harden", "russell westbrook", "anthony davis",
    "dwight howard", "kawhi leonard", "paul george", "damian lillard",
    "zion williamson", "ja morant", "lauri markkanen", "brandon ingram",
]

# 球队中文名（卡淘标题常见）
_TEAM_NAMES_CN = [
    "湖人", "勇士", "凯尔特人", "雄鹿", "掘金", "太阳", "快船", "热火", "公牛",
    "马刺", "76人", "独行侠", "雷霆", "灰熊", "森林狼", "开拓者", "骑士", "猛龙",
    "老鹰", "黄蜂", "魔术", "步行者", "活塞", "奇才", "篮网", "尼克斯", "国王",
    "爵士", "鹈鹕", "火箭", "库里", "詹姆斯", "杜兰特", "字母哥", "文班亚马",
    "东契奇", "塔图姆", "恩比德", "约基奇", "巴特勒", "利拉德", "欧文", "哈登",
    "威少", "保罗", "戴维斯", "布克", "爱德华兹", "莫兰特", "锡安",
]

# 篮球关键词（仅保留篮球专属强信号；系列名如 prizm/donruss 有足球版，不作为命中条件）
_BASKETBALL_KEYWORDS = [
    "nba", "篮球", "basketball", "hoops", "nba hoops", "court kings", "sport kings",
]

# 非篮球品类标记（足球/F1/棒球/漫威/TCG 等，命中即排除）
_NON_BASKETBALL_KEYWORDS = [
    # 足球
    "soccer", "football", "fifa", "world cup", "ucl", "ucc", "uefa", "champions league",
    "premier league", "la liga", "serie a", "bundesliga", "ligue 1", "conmebol",
    "copa", "euro", "match attax", "stickers", "欧洲杯", "欧冠", "世界杯", "英超",
    "意甲", "西甲", "德甲", "法甲", "足球", "美洲杯", "足球卡",
    # 足球俱乐部（中文名）
    "利物浦", "曼城", "皇马", "皇家马德里", "阿森纳", "巴萨", "巴塞罗那", "巴黎圣日耳曼",
    "曼联", "切尔西", "尤文", "拜仁", "国际米兰", "米兰", "多特", "马竞", "热刺",
    "纽卡", "埃弗顿", "维拉", "西汉姆", "狼队", "布莱顿", "水晶宫", "富勒姆",
    "诺丁汉", "伯恩茅斯", "罗马", "那不勒斯", "亚特兰大", "拉齐奥", "塞维利亚",
    "瓦伦西亚", "毕尔巴鄂", "皇家社会", "格拉斯哥", "国家队",
    # F1 / 其他运动
    "f1", "formula", "grand prix", "verstappen", "hamilton", "红牛车队", "赛车",
    "mlb", "baseball", "棒球", "nhl", "hockey", "ice hockey", "nfl", "american football",
    # 非体育
    "marvel", "漫威", "disney", "迪士尼", "pokemon", "pokémon", "宝可梦", "神奇宝贝",
    "one piece", "海贼王", "dragon ball", "龙珠", "naruto", "火影", "star wars",
    "游戏王", "奥特曼", "tcg", "游戏版", "贴纸",
]


def is_basketball_card_title(title: str) -> bool:
    """
    判断卡淘/ebay 标题是否为篮球球星卡（用于过滤足球/F1/漫威等杂项卡）

    匹配规则（任一命中即视为篮球卡）:
      1. 标题含现役 NBA 球员英文名（player_db 450 名）
      2. 标题含常见历史球星名（乔丹/科比/姚明等中英文）
      3. 标题含 NBA 球队英文名或中文名
      4. 标题含篮球关键词（NBA/篮球/basketball/篮球系列名）

    Args:
        title: listing 标题

    Returns:
        True=篮球卡
    """
    if not title:
        return False
    t = title.lower()

    # 0) 负向过滤：明显非篮球品类（足球/F1/漫威等）→ 直接排除
    #    （注意 "euro" 等短词不参与负向匹配，避免误伤；用更长标记）
    for kw in _NON_BASKETBALL_KEYWORDS:
        if kw in t:
            return False

    # 1) 现役 + 退役球员名（子串匹配，避免 "all" 等短名误伤 → 仅匹配 ≥3 字符名）
    for team, players in _ALL_TEAMS.items():
        for player in players:
            name = player[0].lower()
            if len(name) >= 3 and name in t:
                return True

    # 2) 历史球星补充名单
    for star in _HISTORIC_STARS:
        if star in t:
            return True

    # 3) 球队名（英文）
    for team in NBA_TEAMS:
        if team.lower() in t:
            return True
    # 球队名（中文）
    for cn in _TEAM_NAMES_CN:
        if cn in title:
            return True

    # 4) 篮球关键词（篮球专属强信号：NBA/篮球/basketball/Hoops）
    for kw in _BASKETBALL_KEYWORDS:
        if kw in t:
            return True

    return False


def get_all_players() -> list:
    """
    返回所有球员的扁平列表

    Returns:
        List[tuple]: [(name, jersey_number, rookie_year, tier, position, team), ...]
    """
    all_players = []
    for team, players in _ALL_TEAMS.items():
        for player in players:
            all_players.append((*player, team))
    return all_players


def get_player_by_name(name: str) -> dict | None:
    """
    按姓名查找球员（现役 + 退役）

    Args:
        name: 球员姓名

    Returns:
        dict: {name, jersey, rookie_year, tier, position, team, base_price}
        或 None
    """
    for team, players in _ALL_TEAMS.items():
        for (pname, jersey, rc_year, tier, pos) in players:
            if pname.lower() == name.lower():
                price_range = TIER_PRICE_RANGE.get(tier, (1.0, 3.0))
                return {
                    "name": pname,
                    "team": team,
                    "jersey": jersey,
                    "rookie_year": rc_year,
                    "tier": tier,
                    "tier_label": TIER_LABELS.get(tier, "未知"),
                    "position": pos,
                    "base_price_min": price_range[0],
                    "base_price_max": price_range[1],
                }
    return None


def get_players_by_team(team: str) -> list:
    """
    按球队获取球员列表

    Args:
        team: 球队名

    Returns:
        List[dict]
    """
    players = _ALL_TEAMS.get(team, [])
    result = []
    for (pname, jersey, rc_year, tier, pos) in players:
        price_range = TIER_PRICE_RANGE.get(tier, (1.0, 3.0))
        result.append({
            "name": pname,
            "team": team,
            "jersey": jersey,
            "rookie_year": rc_year,
            "tier": tier,
            "tier_label": TIER_LABELS.get(tier, "未知"),
            "position": pos,
            "base_price_min": price_range[0],
            "base_price_max": price_range[1],
        })
    return result


def get_players_by_tier(tier: int) -> list:
    """
    按球星等级筛选球员（现役 + 退役）

    Args:
        tier: 0-5

    Returns:
        List[dict]
    """
    result = []
    for team, players in _ALL_TEAMS.items():
        for (pname, jersey, rc_year, t, pos) in players:
            if t == tier:
                price_range = TIER_PRICE_RANGE.get(t, (1.0, 3.0))
                result.append({
                    "name": pname,
                    "team": team,
                    "jersey": jersey,
                    "rookie_year": rc_year,
                    "tier": t,
                    "tier_label": TIER_LABELS.get(t, "未知"),
                    "position": pos,
                    "base_price_min": price_range[0],
                    "base_price_max": price_range[1],
                })
    return result


def get_player_names_sorted() -> list:
    """
    返回按字母排序的所有球员姓名列表（用于下拉菜单，含退役球星）

    Returns:
        List[str]
    """
    names = []
    for team, players in _ALL_TEAMS.items():
        for (pname, jersey, rc_year, tier, pos) in players:
            names.append(pname)
    return sorted(names)


def get_team_names() -> list:
    """返回所有球队名"""
    return sorted(_ALL_TEAMS.keys())


def get_stats() -> dict:
    """返回数据库统计信息（含退役球星）"""
    total = 0
    tiers = {0: 0, 1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    for team, players in _ALL_TEAMS.items():
        total += len(players)
        for (_, _, _, tier, _) in players:
            tiers[tier] = tiers.get(tier, 0) + 1
    return {
        "total_players": total,
        "total_teams": len(_ALL_TEAMS),
        "by_tier": tiers,
        "by_tier_labels": {TIER_LABELS[k]: v for k, v in tiers.items()},
    }


# ============================================================
# NBA 球员头像映射 (cdn.nba.com headshot IDs)
# ============================================================
_NBA_PLAYER_IDS = {
    # 退役传奇 (2026-08 新增)
    "Michael Jordan": 893,
    "Kobe Bryant": 977,
    "Shaquille O'Neal": 406,
    "Tim Duncan": 1495,
    "Dirk Nowitzki": 1717,
    "Dwyane Wade": 2548,
    "Allen Iverson": 947,
    "Kevin Garnett": 708,
    "Paul Pierce": 1718,
    "Vince Carter": 1713,
    "Carmelo Anthony": 2546,
    "Derrick Rose": 201565,
    "Yao Ming": 2397,
    "Hakeem Olajuwon": 165,
    "Karl Malone": 252,
    "John Stockton": 304,
    "Charles Barkley": 787,
    "Scottie Pippen": 937,
    "Steve Nash": 959,
    "Grant Hill": 747,
    "Reggie Miller": 919,
    "Gary Payton": 936,
    "Jason Kidd": 905,
    "Penny Hardaway": 746,
    "Jerry West": 915,
    # Tier 0 — MVP/超巨
    "LeBron James": 2544,
    "Stephen Curry": 201939,
    "Kevin Durant": 201142,
    "Giannis Antetokounmpo": 203507,
    "Nikola Jokic": 203999,
    "Luka Doncic": 1629029,
    "Jayson Tatum": 1628369,
    "Joel Embiid": 203954,
    "Anthony Davis": 203076,
    "Kawhi Leonard": 202695,
    "Damian Lillard": 203081,
    "Jalen Brunson": 1628973,
    "Shai Gilgeous-Alexander": 1628983,
    "Donovan Mitchell": 1628378,
    # Tier 1 — 全明星
    "Anthony Edwards": 1630162,
    "Ja Morant": 1629630,
    "Zion Williamson": 1629627,
    "Trae Young": 1629027,
    "Devin Booker": 1626164,
    "Bam Adebayo": 1628389,
    "Tyrese Haliburton": 1630169,
    "LaMelo Ball": 1630163,
    "Jaylen Brown": 1627759,
    "Kristaps Porzingis": 204001,
    "Jrue Holiday": 201950,
    "Derrick White": 1628401,
    "Pascal Siakam": 1627783,
    "Brandon Ingram": 1627742,
    "Evan Mobley": 1630596,
    "Darius Garland": 1629636,
    "Jaren Jackson Jr.": 1628991,
    "Domantas Sabonis": 1627734,
    "De'Aaron Fox": 1628368,
    "DeMar DeRozan": 201942,
    "Paolo Banchero": 1631094,
    "Franz Wagner": 1630532,
    "Scottie Barnes": 1630567,
    "Karl-Anthony Towns": 1626157,
    "Mikal Bridges": 1628969,
    "OG Anunoby": 1628384,
    "Jimmy Butler": 202710,
    "James Harden": 201935,
    "Kyrie Irving": 202681,
    "Klay Thompson": 202691,
    "Lauri Markkanen": 1628374,
    "Alperen Sengun": 1630578,
    "Tyrese Maxey": 1630178,
    "Paul George": 202331,
    # Tier 2 — 优质先发
    "Chet Holmgren": 1631097,
    "Jalen Williams": 1631115,
    "Scoot Henderson": 1631112,
    "Brandon Miller": 1631102,
    "Cade Cunningham": 1630595,
    "Jalen Green": 1630224,
    "Jabari Smith Jr.": 1631093,
    "Keegan Murray": 1631099,
    "Ausar Thompson": 1631130,
    "Amen Thompson": 1631131,
    "Jalen Suggs": 1630592,
    "Jalen Duren": 1631095,
    "Jaden Ivey": 1631091,
    "Shaedon Sharpe": 1631104,
    "Devin Vassell": 1630172,
    "Jeremy Sochan": 1631110,
    "Keldon Johnson": 1629640,
    "Desmond Bane": 1630217,
    "Trey Murphy III": 1630530,
    "Herbert Jones": 1630529,
    "Dejounte Murray": 1627749,
    "Jarrett Allen": 1628386,
    "Rudy Gobert": 203497,
    "Julius Randle": 203944,
    "Aaron Gordon": 203932,
    "Michael Porter Jr.": 1629008,
    "Myles Turner": 1626167,
    "Bennedict Mathurin": 1631096,
    "Anfernee Simons": 1629014,
    "Jerami Grant": 203924,
    "Deandre Ayton": 1629028,
    "Jordan Poole": 1629673,
    "Kyle Kuzma": 1628398,
    "Tyler Herro": 1629635,
    "Andrew Wiggins": 203952,
    "Coby White": 1629632,
    "Josh Giddey": 1630581,
    "RJ Barrett": 1629628,
    "Immanuel Quickley": 1630241,
    "Gradey Dick": 1641715,
    "Collin Sexton": 1629012,
    "John Collins": 1628381,
    "Walker Kessler": 1631117,
    "Cam Thomas": 1630568,
    "Nic Claxton": 1629651,
    "D'Angelo Russell": 1626156,
    "Miles Bridges": 1628970,
    "Mark Williams": 1631109,
    "Norman Powell": 203939,
    "Ivica Zubac": 1627826,
    "Austin Reaves": 1630559,
    "Rui Hachimura": 1629060,
    "Zach LaVine": 1628972,
    "Nikola Vucevic": 202696,
    "Fred VanVleet": 1627832,
    "Dillon Brooks": 1628415,
    "CJ McCollum": 203468,
    "Tobias Harris": 202699,
    "Cam Johnson": 1629661,
    "P.J. Washington": 1629023,
    "Daniel Gafford": 1629018,
    "Dereck Lively II": 1641726,
    "Zach Edey": 1641744,
    "Brandon Clarke": 1629634,
    "Jaden McDaniels": 1630183,
    "Luguentz Dort": 1629652,
    "Isaiah Hartenstein": 1628392,
    "Alex Caruso": 1627936,
    "Donte DiVincenzo": 1628978,
    "Naz Reid": 1629675,
    "Malik Monk": 1628370,
    "Draymond Green": 203110,
    "Chris Paul": 101108,
    "Russell Westbrook": 201566,
    "Buddy Hield": 1627741,
    "Steven Adams": 203500,
    "Jonas Valanciunas": 202685,
    "Brook Lopez": 201572,
    "Khris Middleton": 203114,
    "Bobby Portis": 1626171,
    "Victor Wembanyama": 1641705,
    "Stephon Castle": 1642265,
    "Zaccharie Risacher": 1642258,
    "Alex Sarr": 1642259,
    "Reed Sheppard": 1642263,
    "Rob Dillingham": 1642261,
    "Dalton Knecht": 1642260,
    "Bronny James": 1642355,
    "Jared McCain": 1642271,
    "Kyle Filipowski": 1642275,
    "Bub Carrington": 1642267,
    "Isaiah Collier": 1642268,
    "Tidjane Salaun": 1642257,
    "Ron Holland II": 1642266,
    "Matas Buzelis": 1642264,
    "Cody Williams": 1642262,
    "Devin Carter": 1642269,
    "Jaime Jaquez Jr.": 1631179,
    "Brandin Podziemski": 1631178,
    "Keyonte George": 1631180,
    "Scoot Henderson": 1631112,
    "Cam Whitmore": 1641711,
    "GG Jackson": 1641713,
    # Coaches / extras
    "Jonathan Kuminga": 1630228,
    "Moses Moody": 1630545,
    "Trayce Jackson-Davis": 1631212,
    "Christian Braun": 1631123,
    "Peyton Watson": 1631217,
}

_NBA_HEADSHOT_BASE = "https://cdn.nba.com/headshots/nba/latest/1040x760"
_FALLBACK_AVATAR = "https://ui-avatars.com/api/?size=320&bold=true&background=0D8ABC&color=fff&name="


def get_player_image_url(player_name: str) -> str:
    """
    获取球员头像 URL

    降级策略:
      1. NBA 官方 CDN 大头照（140+ 球员）
      2. 彩色首字母头像（ui-avatars.com）

    Args:
        player_name: 球员姓名

    Returns:
        头像图片 URL
    """
    pid = _NBA_PLAYER_IDS.get(player_name)
    if pid:
        return f"{_NBA_HEADSHOT_BASE}/{pid}.png"

    from urllib.parse import quote_plus
    return f"{_FALLBACK_AVATAR}{quote_plus(player_name)}"


# ============================================================
# 动态注册扩展球员（AI 助手联网识别后写入，跨会话生效）
# ============================================================

import os as _os
import json as _json

_EXTRA_PLAYERS_PATH = _os.path.join(
    _os.path.dirname(_os.path.abspath(__file__)),
    "..", "..", "data", "player_extra.json",
)


def register_extra_player(name: str, team: str = "其他球队", jersey: int = 0,
                          rookie_year: int = 0, tier: int = 3,
                          position: str = "", **kwargs) -> None:
    """
    把联网识别出的球员注册进 _ALL_TEAMS（内存立即生效，所有查询函数可用）。
    持久化由 AI 助手的缓存文件完成（data/player_extra.json），启动时自动加载。

    Args:
        name: 球员名（英文）
        team: 球队（英文，如 "Charlotte Hornets"）
        jersey / rookie_year / tier / position: 球员属性
    """
    name = name.strip()
    if not name:
        return
    # 已存在则跳过
    for _players in _ALL_TEAMS.values():
        for (_pname, *_rest) in _players:
            if _pname.lower() == name.lower():
                return
    _ALL_TEAMS.setdefault(team, []).append(
        (name, int(jersey), int(rookie_year), int(tier), position))


def _load_extra_players() -> None:
    """启动时从 data/player_extra.json 加载 AI 助手识别过的球员"""
    try:
        if not _os.path.exists(_EXTRA_PLAYERS_PATH):
            return
        with open(_EXTRA_PLAYERS_PATH, "r", encoding="utf-8") as _f:
            _data = _json.load(_f)
        for _name, _info in (_data or {}).items():
            register_extra_player(
                _name, team=_info.get("team", "其他球队"),
                jersey=int(_info.get("jersey", 0)),
                rookie_year=int(_info.get("rookie_year", 0)),
                tier=int(_info.get("tier", 3)),
                position=_info.get("position", ""),
            )
    except Exception:
        pass


# 模块加载时自动合并扩展球员（必须在 _ALL_TEAMS 构建之后调用）
_load_extra_players()


# ============================================================
# 测试入口
# ============================================================

if __name__ == "__main__":
    stats = get_stats()
    print("=" * 60)
    print("  NBA 全联盟球员数据库")
    print("=" * 60)
    print(f"\n  总计: {stats['total_players']} 名球员, {stats['total_teams']} 支球队")
    print(f"\n  层级分布:")
    for label, count in stats["by_tier_labels"].items():
        bar = "█" * (count // 4)
        print(f"    {label:<10s}: {count:>4d} 人 {bar}")

    # 按 Tier 示例
    print(f"\n  Tier 0 (MVP/超巨) 示例:")
    t0_players = get_players_by_tier(0)
    for p in t0_players[:6]:
        print(f"    {p['name']:<30s} {p['team']:<25s} #{p['jersey']} RC:{p['rookie_year']} ${p['base_price_min']:.0f}-${p['base_price_max']:.0f}")

    print(f"\n  搜索测试:")
    wemby = get_player_by_name("Victor Wembanyama")
    if wemby:
        print(f"    Wemby: {wemby['team']} #{wemby['jersey']} Tier{wemby['tier']} ({wemby['tier_label']}) RC:{wemby['rookie_year']}")

    lebron = get_player_by_name("LeBron James")
    if lebron:
        print(f"    LeBron: {lebron['team']} #{lebron['jersey']} Tier{lebron['tier']} ({lebron['tier_label']}) RC:{lebron['rookie_year']}")

    print(f"\n  球员总数: {len(get_player_names_sorted())}")
    print(f"  前10名字母序: {get_player_names_sorted()[:10]}")
