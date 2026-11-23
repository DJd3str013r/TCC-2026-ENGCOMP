# -*- coding: utf-8 -*-
"""Cache em disco (SQLite) para respostas de RPC e da API do Sourcify. Garante que toda leitura da cadeia no bloco
de referencia seja feita uma unica vez e possa ser reprocessada sem depender do no (e publicada com os dados)."""
import json
import sqlite3
import threading

from .config import CACHE


class Cache:
    def __init__(self, nome):
        self.caminho = CACHE / f"{nome}.sqlite"
        self._local = threading.local()
        con = self._con()
        con.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT NOT NULL)")
        con.commit()

    def _con(self):
        con = getattr(self._local, "con", None)
        if con is None:
            con = sqlite3.connect(self.caminho, timeout=60, check_same_thread=False)
            con.execute("PRAGMA journal_mode=WAL")
            self._local.con = con
        return con

    def obter(self, chave):
        linha = self._con().execute("SELECT v FROM kv WHERE k = ?", (chave,)).fetchone()
        return None if linha is None else json.loads(linha[0])

    def gravar(self, chave, valor):
        con = self._con()
        con.execute("INSERT OR REPLACE INTO kv (k, v) VALUES (?, ?)", (chave, json.dumps(valor)))
        con.commit()

    def chaves(self, prefixo=""):
        return [r[0] for r in self._con().execute("SELECT k FROM kv WHERE k LIKE ?", (prefixo + "%",))]
