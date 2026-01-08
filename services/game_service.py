from sqlitedict import SqliteDict


class GameService:
    def __init__(self, db_path="game_database.sqlite"):
        self.db = SqliteDict(db_path, autocommit=True)

    def _key(self, guild_id: int, channel_id: int | None) -> str:
        return f"g:{guild_id}:vc:{channel_id if channel_id is not None else '*'}"

    def _load(self, guild_id: int, channel_id: int | None) -> dict:
        return self.db.get(
            self._key(guild_id, channel_id), {"game_name": None, "characters": {}}
        )

    def _save(self, guild_id: int, channel_id: int | None, cfg: dict) -> None:
        self.db[self._key(guild_id, channel_id)] = cfg

    def set_game(self, guild_id: int, name: str, channel_id: int | None = None) -> None:
        cfg = self._load(guild_id, channel_id)
        cfg["game_name"] = name.strip()
        self._save(guild_id, channel_id, cfg)

    def set_character(
        self, guild_id: int, user_id: int, character: str, channel_id: int | None = None
    ) -> None:
        cfg = self._load(guild_id, channel_id)
        cfg["characters"][str(user_id)] = character.strip()
        self._save(guild_id, channel_id, cfg)

    def get_game(self, guild_id: int, channel_id: int | None = None) -> str | None:
        cfg = self._load(guild_id, channel_id)
        return cfg["game_name"]

    def get_character(
        self, guild_id: int, user_id: int, channel_id: int | None = None
    ) -> str | None:
        cfg = self._load(guild_id, channel_id)
        return cfg["characters"].get(str(user_id))

    def get_mapping(self, guild_id: int, channel_id: int) -> dict:
        cfg = self._load(guild_id, channel_id)

        game_name = cfg["game_name"]
        characters = cfg["characters"].copy()

        return {"game_name": game_name, "characters": characters}
