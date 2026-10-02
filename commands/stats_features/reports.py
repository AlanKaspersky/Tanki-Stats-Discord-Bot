import discord
import logging


logger = logging.getLogger(__name__)


class ReportsMixin:
    RANKS = [
        (0, "Recruit"),
        (100, "Private"),
        (500, "Corporal"),
        (1500, "Lance Corporal"),
        (3700, "Master Corporal"),
        (7100, "Sergeant"),
        (12300, "Staff Sergeant"),
        (20000, "Master Sergeant"),
        (29000, "First Sergeant"),
        (41000, "Sergeant Major"),
        (57000, "Warrant Officer 1"),
        (76000, "Warrant Officer 2"),
        (98000, "Warrant Officer 3"),
        (125000, "Warrant Officer 4"),
        (156000, "Warrant Officer 5"),
        (192000, "Junior Lieutenant"),
        (233000, "Lieutenant"),
        (280000, "Senior Lieutenant"),
        (332000, "Captain"),
        (390000, "Major"),
        (455000, "Lieutenant Colonel"),
        (527000, "Colonel"),
        (606000, "Brigadier"),
        (692000, "Major General"),
        (787000, "Lieutenant General"),
        (889000, "General"),
        (1000000, "Marshal"),
        (1122000, "Field Marshal"),
        (1255000, "Commander"),
        (1400000, "Generalissimo"),
        (1600000, "Legend"),
    ]

    def get_rank_title(self, score: int) -> str:
        """
        Возвращает название звания (на английском) по количеству опыта (score).
        """
        if score >= 1600000:
            levels = (score - 1600000) // 200000 + 1
            return f"Legend {levels}"

        for i in range(len(self.RANKS) - 1, -1, -1):
            if self.RANKS[i][0] <= score:
                return self.RANKS[i][1]
        return "Recruit"

    def calculate_difference(self, current: dict, previous: dict):
        """Вычисляет разницу между текущей и предыдущей статистикой"""
        if not previous:
            previous = {
                "earnedCrystals": 0,
                "kills": 0,
                "deaths": 0,
                "caughtGolds": 0,
                "score": 0,
                "modesPlayed": [],
                "turretsPlayed": [],
                "hullsPlayed": [],
                "dronesPlayed": [],
                "resistanceModules": [],
                "suppliesUsage": [],
            }

        current_merged = current.copy()
        arrays_to_merge = ["hullsPlayed", "turretsPlayed", "resistanceModules"]
        for array_key in arrays_to_merge:
            if array_key in current_merged and isinstance(
                current_merged[array_key], list
            ):
                current_merged[array_key] = self.accounts_manager._merge_items_by_name(
                    current_merged[array_key]
                )

        diff = {}

        basic_fields = ["earnedCrystals", "kills", "deaths", "caughtGolds", "score"]
        for field in basic_fields:
            current_val = current_merged.get(field, 0)
            previous_val = previous.get(field, 0)
            diff_val = current_val - previous_val
            diff[field] = diff_val

        diff["modes"] = {}
        current_modes = {
            mode["type"]: mode for mode in current_merged.get("modesPlayed", [])
        }
        previous_modes = {
            mode["type"]: mode for mode in previous.get("modesPlayed", [])
        }

        for mode_type, current_mode in current_modes.items():
            previous_mode = previous_modes.get(mode_type, {})
            diff["modes"][mode_type] = {
                "scoreEarned": current_mode.get("scoreEarned", 0)
                - previous_mode.get("scoreEarned", 0)
            }

        for mode_type, previous_mode in previous_modes.items():
            if mode_type not in diff["modes"]:
                diff["modes"][mode_type] = {
                    "scoreEarned": -previous_mode.get("scoreEarned", 0)
                }

        diff["turrets"] = {}
        current_turrets = {
            turret.get("name"): turret
            for turret in current_merged.get("turretsPlayed", [])
            if turret.get("name")
        }
        previous_turrets = {
            turret.get("name"): turret
            for turret in previous.get("turretsPlayed", [])
            if turret.get("name")
        }

        for turret_name, current_turret in current_turrets.items():
            previous_turret = previous_turrets.get(turret_name, {})
            diff["turrets"][turret_name] = {
                "name": current_turret.get("name", ""),
                "scoreEarned": current_turret.get("scoreEarned", 0)
                - previous_turret.get("scoreEarned", 0),
            }

        diff["hulls"] = {}
        current_hulls = {
            hull.get("name"): hull
            for hull in current_merged.get("hullsPlayed", [])
            if hull.get("name")
        }
        previous_hulls = {
            hull.get("name"): hull
            for hull in previous.get("hullsPlayed", [])
            if hull.get("name")
        }

        for hull_name, current_hull in current_hulls.items():
            previous_hull = previous_hulls.get(hull_name, {})
            diff["hulls"][hull_name] = {
                "name": current_hull.get("name", ""),
                "scoreEarned": current_hull.get("scoreEarned", 0)
                - previous_hull.get("scoreEarned", 0),
            }

        diff["resistance"] = {}
        current_resistance = {
            module.get("name"): module
            for module in current_merged.get("resistanceModules", [])
            if module.get("name")
        }
        previous_resistance = {
            module.get("name"): module
            for module in previous.get("resistanceModules", [])
            if module.get("name")
        }

        for module_name, current_module in current_resistance.items():
            previous_module = previous_resistance.get(module_name, {})
            diff["resistance"][module_name] = {
                "name": current_module.get("name", ""),
                "scoreEarned": current_module.get("scoreEarned", 0)
                - previous_module.get("scoreEarned", 0),
            }

        diff["drones"] = {}
        current_drones = {
            drone["id"]: drone
            for drone in current.get("dronesPlayed", [])
            if drone.get("id")
        }
        previous_drones = {
            drone["id"]: drone
            for drone in previous.get("dronesPlayed", [])
            if drone.get("id")
        }

        for drone_id, current_drone in current_drones.items():
            previous_drone = previous_drones.get(drone_id, {})
            diff["drones"][drone_id] = {
                "name": current_drone.get("name", ""),
                "scoreEarned": current_drone.get("scoreEarned", 0)
                - previous_drone.get("scoreEarned", 0),
            }

        diff["supplies"] = {}
        current_supplies = {
            supply["id"]: supply
            for supply in current.get("suppliesUsage", [])
            if supply.get("id")
        }
        previous_supplies = {
            supply["id"]: supply
            for supply in previous.get("suppliesUsage", [])
            if supply.get("id")
        }

        for supply_id, current_supply in current_supplies.items():
            previous_supply = previous_supplies.get(supply_id, {})
            diff["supplies"][supply_id] = {
                "name": current_supply.get("name", ""),
                "usages": current_supply.get("usages", 0)
                - previous_supply.get("usages", 0),
            }

        return diff

    def create_embed(self, diff_stats, current_stats, language="ru"):

        hull_emojis = {
            "Викинг": "<:93:1518306145134055687>",
            "Крусейдер": "<:121:1518322443335237722>",
            "Паладин": "<:96:1518306924326813839>",
            "Васп": "<:92:1518305709651923034>",
            "Хорнет": "<:90:1518305702945226882>",
            "Хантер": "<:95:1518306711310565580>",
            "Мамонт": "<:100:1518308535211921510>",
            "Арес": "<:99:1518307989713322044>",
            "Диктатор": "<:97:1518307464808890559>",
            "Титан": "<:98:1518307713946222884>",
            "Хоппер": "<:91:1518305705898020874>",
            "Джаггернаут": "<:101:1518308716036886708>",
        }

        turret_emojis = {
            "Смоки": "<:18:1515191126347354223>",
            "Рикошет": "<:8_:1515190296223154318>",
            "Гром": "<:3_:1515188663112433834>",
            "Рельса": "<:17:1515191064603132057>",
            "Изида": "<:2_:1515188667709132940>",
            "Магнум": "<:16:1515191009447907501>",
            "Твинс": "<:9_:1515190407586119771>",
            "Страйкер": "<:4_:1515188664932634644>",
            "Гаусс": "<:15:1515190905613582497>",
            "Вулкан": "<:14:1515190820729393182>",
            "Шафт": "<:6_:1515190070972518581>",
            "Молот": "<:7_:1515190192019865660>",
            "Огнемёт": "<:11:1515190572116082738>",
            "Скорпион": "<:12:1515190642400170165>",
            "Фриз": "<:10:1515190499361685594>",
            "Тесла": "<:5_:1515189779543756960>",
            "Цунами": "<:13:1515190755105177753>",
            "Терминатор": "<:20:1515191467042275338>",
        }

        drone_emojis = {
            "Кризис": "<:127:1518327371046977596>",
            "Брут": "<:131:1518327407214460938>",
            "Диверсант": "<:129:1518327375748665574>",
            "Ловкач": "<:124:1518327362226487438>",
            "Механик": "<:130:1518327377288106064>",
            "Бустер": "<:125:1518327364399136789>",
            "Защитник": "<:126:1518327365888118784>",
            "Гиперион": "<:128:1518327373882462491>",
            "Оракул": "<:132:1518327408875405543>",
            "Кризис ХТ": "<:122:1518327357772136719>",
            "Гиперион ХТ": "<:123:1518327359193743401>",
        }

        resistance_emojis = {
            "Сокол": "<:47:1442928291362373673>",
            "Дельфин": "<:41:1442928299503517809>",
            "Лев": "<:40:1442928301009272993>",
            "Гризли": "<:45:1442928294570758184>",
            "Грифон": "<:48:1442928289575604366>",
            "Сова": "<:49:1442928288174444594>",
            "Касатка": "<:42:1442928297850834985>",
            "Гриф": "<:46:1442928292960272524>",
            "Паук": "<:44:1442928284768927767>",
            "Акула": "<:43:1442928296101810249>",
            "Броненосец": "<:33:1442938561505525821>",
            "Волк": "<:38:1442928305383673938>",
            "Лис": "<:34:1442928312338087966>",
            "Барсук": "<:35:1442928310345793778>",
            "Оцелот": "<:36:1442928308231864391>",
            "Ласка": "<:37:1442928306939760691>",
            "Пантера": "<:39:1442928302632472678>",
            "Орёл": "<:50:1442928286257774683>",
            "Ворон": "<:32:1493454382161723424>",
            "Спектр B": "<:1_:1515186817165426758>",
            "Спектр A": "<:1_:1515186817165426758>",
            "Спектр M": "<:1_:1515186817165426758>",
            "Спектр C": "<:1_:1515186817165426758>",
            "Спектр Демон": "<:1_:1515186817165426758>",
            "Спектр Лорд": "<:1_:1515186817165426758>",
        }

        mode_emojis = {
            "DM": "<:110:1518310748986544390>",
            "TDM": "<:107:1518310058134339695>",
            "CTF": "<:108:1518310355418480641>",
            "CP": "<:105:1518309104274247851>",
            "AS": "<:109:1518310539921457463>",
            "RUGBY": "<:103:1518309100839239851>",
            "JGR": "<:102:1518309097701773453>",
            "TJR": "<:106:1518309466871959603>",
            "SGE": "<:104:1518309102646988911>",
        }

        supply_emojis = {
            "Мина": "<:119:1518313993960292502>",
            "Повышенный урон": "<:117:1518313875211157594>",
            "Повышенная защита": "<:116:1518313843489505452>",
            "Ускорение": "<:118:1518313918102114415>",
            "Ядерная энергия": "<:134:1518622911634608218>",
            "Золотой ящик": "<:120:1518314168325767399>",
            "Ремкомплект": "<:115:1518313796219834439>",
            "Бомба": "<:67:1442939999883493387>",
            "Царь": "<:62:1442939983399751752>",
            "Снежок": "<:63:1442939985643962711>",
            "Мортира": "<:66:1442939992002269275>",
            "Салют": "<:65:1442939989276229652>",
            "Тыква": "<:64:1442939987346722967>",
            "Медик": "<:68:1486116769407176754>",
            "Дым": "<:70:1515200717437145098>",
            "Телепорт": "<:69:1515200920097656862>",
        }

        """Создает красивый эмбед со статистикой."""
        embed = discord.Embed(
            title="Statistics" if self._is_english(language) else "Статистика",
            color=0xFFFFFF,
            timestamp=discord.utils.utcnow(),
        )

        total_score = current_stats.get("score", 0)
        embed.description = (
            f"**Total score:** {total_score:,}"
            if self._is_english(language)
            else f"**Общий счет:** {total_score:,}"
        )

        if not diff_stats:
            embed.add_field(
                name="Information" if self._is_english(language) else "Информация",
                value=(
                    "No comparison data (first run or stats have not changed)"
                    if self._is_english(language)
                    else "Нет данных для сравнения (первый запуск или данные не изменились)"
                ),
                inline=False,
            )
            return embed

        basic_text = []
        if diff_stats.get("earnedCrystals", 0) != 0:
            basic_text.append(
                f"<:113:1518312250962608238> {'Crystal' if self._is_english(language) else 'Прирост кристаллов'}: {diff_stats['earnedCrystals']:+}"
            )
        if diff_stats.get("kills", 0) != 0:
            basic_text.append(
                f"<:111:1518311667530858617> {'Kill' if self._is_english(language) else 'Прирост убийств'}: {diff_stats['kills']:+}"
            )
        if diff_stats.get("deaths", 0) != 0:
            basic_text.append(
                f"<:112:1518312025170907156> {'Death' if self._is_english(language) else 'Прирост смертей'}: {diff_stats['deaths']:+}"
            )
        if diff_stats.get("caughtGolds", 0) != 0:
            basic_text.append(
                f"<:114:1518312915252285490> {'Gold Box' if self._is_english(language) else 'Поймано голдов'}: {diff_stats['caughtGolds']:+}"
            )

        if basic_text:
            embed.add_field(
                name="**Personal stats**"
                if self._is_english(language)
                else "**Личная статистика**",
                value="\n".join(basic_text),
                inline=False,
            )

        modes_text = []
        modes_data = []
        mode_translations = {
            "DM": "Каждый за себя",
            "TDM": "Командный бой",
            "CTF": "Захват флага",
            "CP": "Контроль точек",
            "AS": "Штурм",
            "RUGBY": "Регби",
            "JGR": "Соло Джаггернаут",
            "TJR": "Джаггернаут",
            "SGE": "Осада",
        }
        mode_translations_en = {
            "DM": "Deathmatch",
            "TDM": "Team Deathmatch",
            "CTF": "Capture the Flag",
            "CP": "Control Points",
            "AS": "Assault",
            "RUGBY": "Rugby",
            "JGR": "Solo Juggernaut",
            "TJR": "Team Juggernaut",
            "SGE": "Siege",
        }

        for mode_type, mode_diff in diff_stats.get("modes", {}).items():
            score_diff = mode_diff.get("scoreEarned", 0)
            if score_diff != 0:
                mode_name = (
                    mode_translations_en
                    if self._is_english(language)
                    else mode_translations
                ).get(mode_type, mode_type)
                emoji = mode_emojis.get(mode_type, "<:default:123456789012345722>")
                modes_data.append((mode_name, score_diff, emoji))

        modes_data.sort(key=lambda x: x[1], reverse=True)
        for name, score, emoji in modes_data:
            modes_text.append(f"{emoji} {name}: {score:+}")

        if modes_text:
            embed.add_field(
                name="**Mode score gain**"
                if self._is_english(language)
                else "**Прирост по режимам**",
                value="\n".join(modes_text),
                inline=False,
            )

        turrets_text = []
        turrets_data = []
        for turret_id, turret_diff in diff_stats.get("turrets", {}).items():
            score_diff = turret_diff.get("scoreEarned", 0)
            if score_diff != 0:
                emoji = turret_emojis.get(
                    turret_diff["name"], "<:default:123456789012345722>"
                )
                turrets_data.append(
                    (
                        self._localized_item_name(turret_diff["name"], language),
                        score_diff,
                        emoji,
                    )
                )

        turrets_data.sort(key=lambda x: x[1], reverse=True)
        for name, score, emoji in turrets_data:
            turrets_text.append(f"{emoji} {name}: {score:+}")

        if turrets_text:
            embed.add_field(
                name="**Turret score gain**"
                if self._is_english(language)
                else "**Прирост по пушкам**",
                value="\n".join(turrets_text),
                inline=False,
            )

        hulls_text = []
        hulls_data = []
        for hull_name, hull_diff in diff_stats.get("hulls", {}).items():
            score_diff = hull_diff.get("scoreEarned", 0)
            if score_diff != 0:
                emoji = hull_emojis.get(
                    hull_diff["name"], "<:default:123456789012345722>"
                )
                hulls_data.append(
                    (
                        self._localized_item_name(hull_diff["name"], language),
                        score_diff,
                        emoji,
                    )
                )

        hulls_data.sort(key=lambda x: x[1], reverse=True)
        for name, score, emoji in hulls_data:
            hulls_text.append(f"{emoji} {name}: {score:+}")

        if hulls_text:
            embed.add_field(
                name="**Hull score gain**"
                if self._is_english(language)
                else "**Прирост по корпусам**",
                value="\n".join(hulls_text),
                inline=False,
            )

        drones_text = []
        drones_data = []
        for drone_id, drone_diff in diff_stats.get("drones", {}).items():
            score_diff = drone_diff.get("scoreEarned", 0)
            if score_diff != 0:
                emoji = drone_emojis.get(
                    drone_diff["name"], "<:default:123456789012345722>"
                )
                drones_data.append(
                    (
                        self._localized_item_name(drone_diff["name"], language),
                        score_diff,
                        emoji,
                    )
                )

        drones_data.sort(key=lambda x: x[1], reverse=True)
        for name, score, emoji in drones_data:
            drones_text.append(f"{emoji} {name}: {score:+}")

        if drones_text:
            embed.add_field(
                name="**Drone score gain**"
                if self._is_english(language)
                else "**Прирост по дронам**",
                value="\n".join(drones_text),
                inline=False,
            )

        resistance_text = []
        resistance_data = []
        for module_name, module_diff in diff_stats.get("resistance", {}).items():
            score_diff = module_diff.get("scoreEarned", 0)
            if score_diff != 0:
                emoji = resistance_emojis.get(
                    module_diff["name"], "<:default:123456789012345722>"
                )
                resistance_data.append(
                    (
                        self._localized_item_name(module_diff["name"], language),
                        score_diff,
                        emoji,
                    )
                )
        resistance_data.sort(key=lambda x: x[1], reverse=True)
        for name, score, emoji in resistance_data:
            resistance_text.append(f"{emoji} {name}: {score:+}")

        if resistance_text:
            embed.add_field(
                name="**Resistance module score gain**"
                if self._is_english(language)
                else "**Прирост по модулям**",
                value="\n".join(resistance_text),
                inline=False,
            )

        supplies_text = []
        supplies_data = []
        for supply_id, supply_diff in diff_stats.get("supplies", {}).items():
            usages_diff = supply_diff.get("usages", 0)
            if usages_diff != 0:
                emoji = supply_emojis.get(
                    supply_diff["name"], "<:default:123456789012345722>"
                )
                supplies_data.append(
                    (
                        self._localized_item_name(supply_diff["name"], language),
                        usages_diff,
                        emoji,
                    )
                )

        supplies_data.sort(key=lambda x: x[1], reverse=True)
        for name, usages, emoji in supplies_data:
            supplies_text.append(f"{emoji} {name}: {usages:+}")

        if supplies_text:
            embed.add_field(
                name="**Supply usage gain**"
                if self._is_english(language)
                else "**Прирост по припасам**",
                value="\n".join(supplies_text),
                inline=False,
            )

        embed.set_footer(
            text=(
                "⚠️ Stats may be delayed. Check the game for the most accurate data. Contact Kaspersky if you have any issues!"
                if self._is_english(language)
                else "⚠️ Информация может обновляться с задержкой. Точные данные проверяйте в самой игре. В случае проблем обращайтесь к Kaspersky!"
            )
        )

        return embed
