"""MemoryClient — lm-mem 面向对象客户端。

包装底层 ChromaDB 操作为简洁的实例方法，返回 Python dict 而非 JSON 字符串。
"""
from __future__ import annotations

import json
import time
import uuid

from lm_mem.backend import collection_for_url, get_collection
from lm_mem.memory_utils import (
    clauses,
    coerce_scalar,
    combine,
    DEDUP_THRESHOLD,
    hits_to_records,
    is_expired,
    MD_PREFIX,
    memory_to_record,
    messages_to_text,
    metadata_filter_clauses,
    OVERFETCH,
    parse_metadata,
    scope_meta,
    SCOPE_KEYS,
    scope_where,
    user_metadata,
)


class MemoryClient:
    """lm-mem 面向对象客户端。

    用法::

        from lm_mem import MemoryClient

        client = MemoryClient()

        # 保存记忆
        client.add("用户偏好 pytest", user_id="u1")
        # 或从对话历史保存
        client.add(messages=[{"role":"user","content":"I like cats"}], user_id="u1")

        # 检索
        results = client.search("测试框架偏好", user_id="u1")
        for r in results["items"]:
            print(r["content"], r["similarity"])

        # 查看、更新、删除
        info = client.get("mem-id-xxx")
        client.update("mem-id-xxx", content="新内容")
        client.delete("mem-id-xxx")

    默认连接由 LM_MEM_BACKEND_URL(pytest 下为嵌入式)决定的共享后端;
    传 url 可显式指向某个后端,如 MemoryClient(url="http://127.0.0.1:8901")。
    """

    def __init__(self, url: str = ""):
        self._url = url.strip()
        self._collection = None

    def _col(self):
        """获取本客户端使用的集合。

        传了 url → 用该 url 的独立连接(优先于 LM_MEM_BACKEND_URL 环境变量);
        未传 → 用全局共享后端(由 LM_MEM_BACKEND_URL 决定,pytest 下为嵌入式)。
        """
        if not self._url:
            return get_collection()
        if self._collection is None:
            self._collection = collection_for_url(self._url)
        return self._collection

    # ── 写 ────────────────────────────────────────────────

    def add(
        self,
        content: str = "",
        *,
        messages: list | str = "",
        user_id: str = "",
        agent_id: str = "",
        app_id: str = "",
        run_id: str = "",
        tags: str = "",
        metadata: str = "",
        ttl_seconds: int = 0,
        force: bool = False,
    ) -> dict:
        """保存一条记忆。

        Args:
            content: 要记住的文本（与 messages 二选一）。
            messages: 对话历史（list[dict] 或 JSON 数组字符串）。
            user_id / agent_id / app_id / run_id: 作用域。
            tags: 逗号分隔的标签。
            metadata: 附加元数据 JSON 对象字符串。
            ttl_seconds: >0 时记忆在该秒数后过期。
            force: True 跳过查重。

        Returns:
            成功: {"id": "..."}
            查重命中: {"duplicate_id": "...", "similarity": 0.95, ...}
        """
        text = content.strip() if content else ""
        if not text and messages:
            text = messages_to_text(messages)
        if not text:
            raise ValueError("content 与 messages 均为空，没有可保存的内容。")

        scope_clauses = clauses(user_id, agent_id, app_id, run_id)
        if not force:
            if dup := self._check_duplicate(text, scope_clauses):
                return dup

        mem_id = str(uuid.uuid4())
        now = time.time()
        meta: dict = {"created_at": now, "tags": tags.strip()}
        meta.update(scope_meta(user_id, agent_id, app_id, run_id))
        meta.update(parse_metadata(metadata))
        if ttl_seconds and ttl_seconds > 0:
            meta["expires_at"] = now + ttl_seconds
        self._col().add(ids=[mem_id], documents=[text], metadatas=[meta])
        return {"id": mem_id}

    def update(
        self,
        mem_id: str,
        *,
        content: str = "",
        metadata: str = "",
        tags: str = "",
        ttl_seconds: int = 0,
    ) -> dict:
        """更新记忆。

        Args:
            mem_id: 记忆 id。
            content: 新文本（留空不改）。
            metadata: JSON 对象字符串，合并进现有元数据。
            tags: 新的逗号分隔标签。
            ttl_seconds: >0 续期；<0 清除过期（永久）；0 不改动。
        """
        existing = self._col().get(ids=[mem_id], include=["documents", "metadatas"])
        if not existing["ids"]:
            raise ValueError(f"未找到 id={mem_id} 的记忆。")
        meta = existing["metadatas"][0] or {}
        now = time.time()
        meta["updated_at"] = now
        if tags:
            meta["tags"] = tags.strip()
        if metadata:
            meta.update(parse_metadata(metadata))
        if ttl_seconds > 0:
            meta["expires_at"] = now + ttl_seconds
        elif ttl_seconds < 0:
            meta["expires_at"] = 0
        doc = content.strip() if content else existing["documents"][0]
        self._col().update(ids=[mem_id], documents=[doc], metadatas=[meta])
        return {"id": mem_id}

    def delete(self, mem_id: str) -> dict:
        """按 id 删除单条记忆。"""
        if not self._col().get(ids=[mem_id])["ids"]:
            raise ValueError(f"未找到 id={mem_id} 的记忆。")
        self._col().delete(ids=[mem_id])
        return {"id": mem_id}

    def delete_all(
        self,
        *,
        user_id: str = "",
        agent_id: str = "",
        app_id: str = "",
        run_id: str = "",
    ) -> dict:
        """批量删除作用域内的所有记忆。"""
        where = scope_where(user_id, agent_id, app_id, run_id)
        if where is None:
            raise ValueError("必须指定至少一个作用域(user_id/agent_id/app_id/run_id)。")
        hits = self._col().get(where=where)
        n = len(hits["ids"])
        if n > 0:
            self._col().delete(where=where)
        return {"deleted": n}

    def delete_entity(self, entity_type: str, entity_id: str) -> dict:
        """删除某个实体及其所有记忆。"""
        key = f"{entity_type}_id"
        if key not in SCOPE_KEYS:
            raise ValueError(f"无效的 entity_type={entity_type}(应为 user/agent/app/run)。")
        hits = self._col().get(where={key: entity_id})
        if not hits["ids"]:
            raise ValueError(f"未找到 {entity_type}={entity_id} 的记忆。")
        n = len(hits["ids"])
        self._col().delete(where={key: entity_id})
        return {"deleted": n}

    def purge_expired(self) -> dict:
        """清理所有过期记忆。"""
        res = self._col().get(include=["metadatas"])
        now = time.time()
        expired_ids = [
            mem_id
            for mem_id, meta in zip(res["ids"], res["metadatas"])
            if is_expired(meta, now)
        ]
        if expired_ids:
            self._col().delete(ids=expired_ids)
        return {"deleted": len(expired_ids)}

    # ── 读 ────────────────────────────────────────────────

    def search(
        self,
        query: str,
        *,
        limit: int = 5,
        user_id: str = "",
        agent_id: str = "",
        app_id: str = "",
        run_id: str = "",
        metadata_filter: str = "",
    ) -> dict:
        """按语义相似度检索记忆。"""
        col = self._col()
        count = col.count()
        if count == 0:
            return {"items": []}
        where_clauses = clauses(user_id, agent_id, app_id, run_id)
        where_clauses += metadata_filter_clauses(metadata_filter)
        where = combine(where_clauses)
        # 过取以便过滤过期项;但 n_results 不能超过集合大小(旧版 Chroma 会报错)。
        n = min(count, max(limit * OVERFETCH, limit + 10, 100))
        res = col.query(query_texts=[query], n_results=n, where=where)
        items = hits_to_records(res, limit)
        return {"items": items}

    def get(self, mem_id: str) -> dict:
        """按 id 获取单条记忆。"""
        res = self._col().get(ids=[mem_id], include=["documents", "metadatas"])
        if not res["ids"]:
            raise ValueError(f"未找到 id={mem_id} 的记忆。")
        return memory_to_record(res["ids"][0], res["documents"][0], res["metadatas"][0])

    def list(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        user_id: str = "",
        agent_id: str = "",
        app_id: str = "",
        run_id: str = "",
        metadata_filter: str = "",
    ) -> dict:
        """列出记忆，支持分页与过滤。"""
        where_clauses = clauses(user_id, agent_id, app_id, run_id)
        where_clauses += metadata_filter_clauses(metadata_filter)
        where = combine(where_clauses)
        res = self._col().get(
            where=where, limit=limit, offset=offset, include=["documents", "metadatas"]
        )
        now = time.time()
        items = [
            memory_to_record(mem_id, doc, meta)
            for mem_id, doc, meta in zip(res["ids"], res["documents"], res["metadatas"])
            if not is_expired(meta, now)
        ]
        return {"items": items, "offset": offset}

    # ── 实体 / 统计 ───────────────────────────────────────

    def list_entities(self, entity_type: str = "") -> dict:
        """列出已存储的实体。"""
        res = self._col().get(include=["metadatas"])
        buckets = {k: set() for k in SCOPE_KEYS}
        for meta in res["metadatas"]:
            for key in SCOPE_KEYS:
                if meta and meta.get(key):
                    buckets[key].add(meta[key])
        if entity_type:
            key = f"{entity_type}_id"
            if key not in SCOPE_KEYS:
                raise ValueError(f"无效的 entity_type={entity_type}。")
            return {"entities": {key: sorted(buckets[key])}}
        return {"entities": {k: sorted(buckets[k]) for k in SCOPE_KEYS}}

    def stats(
        self,
        *,
        user_id: str = "",
        agent_id: str = "",
        app_id: str = "",
        run_id: str = "",
    ) -> dict:
        """统计记忆库。"""
        where = scope_where(user_id, agent_id, app_id, run_id)
        res = self._col().get(where=where, include=["metadatas"])
        metas = res["metadatas"]
        total = len(res["ids"])
        now = time.time()
        expired = sum(1 for m in metas if is_expired(m, now))
        active = total - expired
        scope_counts = {k: {} for k in SCOPE_KEYS}
        tag_counts: dict[str, int] = {}
        category_counts: dict[str, int] = {}
        for m in metas:
            m = m or {}
            if is_expired(m, now):
                continue
            for key in SCOPE_KEYS:
                if m.get(key):
                    scope_counts[key][m[key]] = scope_counts[key].get(m[key], 0) + 1
            for t in (m.get("tags") or "").split(","):
                t = t.strip()
                if t:
                    tag_counts[t] = tag_counts.get(t, 0) + 1
            cat = m.get(f"{MD_PREFIX}category")
            if cat is not None:
                category_counts[cat] = category_counts.get(cat, 0) + 1
        return {
            "counts": {"total": total, "active": active, "expired": expired},
            "scope": scope_counts,
            "tags": tag_counts,
            "categories": category_counts,
        }

    def get_user_context(
        self,
        *,
        user_id: str = "",
        limit: int = 10,
    ) -> dict:
        """获取用户核心上下文（偏好/身份/环境）。

        user_id 为空时只返回**无 user_id 归属的全局记忆**，不会串出其他用户的
        画像（防跨用户泄露）；传了 user_id 则限定该用户。
        """
        where_scope = scope_where(user_id, "", "", "")
        core_categories = ("preference", "identity", "environment")
        now = time.time()
        all_hits: list[tuple[str, str, dict]] = []
        seen_ids: set[str] = set()
        for cat in core_categories:
            cat_clauses: list[dict] = []
            if where_scope is not None:
                if "$and" in where_scope:
                    cat_clauses.extend(where_scope["$and"])
                else:
                    cat_clauses.append(where_scope)
            cat_clauses.append({f"{MD_PREFIX}category": cat})
            where = combine(cat_clauses)
            res = self._col().get(where=where, include=["documents", "metadatas"])
            for mem_id, doc, meta in zip(res["ids"], res["documents"], res["metadatas"]):
                if mem_id in seen_ids or is_expired(meta, now):
                    continue
                # 未指定 user_id 时,排除任何带 user_id 归属的记忆,只留全局记忆,
                # 避免无作用域查询把其他用户的画像一并返回。
                if not user_id and (meta or {}).get("user_id"):
                    continue
                seen_ids.add(mem_id)
                all_hits.append((mem_id, doc, meta or {}))
        importance_rank = {"high": 3, "medium": 2, "low": 1}
        all_hits.sort(
            key=lambda x: (
                -importance_rank.get(x[2].get(f"{MD_PREFIX}importance", ""), 0),
                -(x[2].get("created_at") or 0),
            )
        )
        items = [memory_to_record(mid, doc, meta) for mid, doc, meta in all_hits[:limit]]
        return {"items": items}

    # ── 导入导出 ──────────────────────────────────────────

    def export(
        self,
        *,
        fmt: str = "json",
        user_id: str = "",
        agent_id: str = "",
        app_id: str = "",
        run_id: str = "",
    ) -> dict:
        """批量导出记忆。"""
        fmt = fmt.lower().strip()
        if fmt not in ("json", "csv"):
            raise ValueError(f"无效的 fmt={fmt}(应为 json 或 csv)。")
        where = scope_where(user_id, agent_id, app_id, run_id)
        res = self._col().get(where=where, include=["documents", "metadatas"])
        records = []
        for mem_id, doc, meta in zip(res["ids"], res["documents"], res["metadatas"]):
            meta = meta or {}
            rec: dict = {
                "id": mem_id,
                "content": doc,
                "tags": meta.get("tags", ""),
                "created_at": meta.get("created_at"),
                "updated_at": meta.get("updated_at"),
                "expires_at": meta.get("expires_at"),
            }
            for key in SCOPE_KEYS:
                if meta.get(key):
                    rec[key] = meta[key]
            rec["metadata"] = user_metadata(meta)
            records.append(rec)
        if fmt == "json":
            return {"records": records}
        import csv as _csv
        import io as _io
        buf = _io.StringIO()
        fields = ["id", "content", "tags", "created_at", "updated_at", "expires_at"]
        fields += list(SCOPE_KEYS) + ["metadata"]
        writer = _csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for rec in records:
            row = dict(rec)
            row["metadata"] = json.dumps(rec["metadata"], ensure_ascii=False)
            writer.writerow(row)
        return {"csv": buf.getvalue()}

    def import_data(
        self,
        data: str,
        *,
        fmt: str = "json",
        overwrite: bool = False,
        new_ids: bool = False,
    ) -> dict:
        """从导出数据批量导入记忆。"""
        fmt = fmt.lower().strip()
        if fmt not in ("json", "csv"):
            raise ValueError(f"无效的 fmt={fmt}(应为 json 或 csv)。")
        if overwrite and new_ids:
            raise ValueError("overwrite 与 new_ids 互斥。")
        if fmt == "json":
            try:
                records = json.loads(data)
            except json.JSONDecodeError as exc:
                raise ValueError(f"data 不是合法 JSON:{exc}") from exc
            if not isinstance(records, list):
                raise ValueError("data 必须是 JSON 数组。")
        else:
            import csv as _csv
            import io as _io
            try:
                reader = _csv.DictReader(_io.StringIO(data))
                records = list(reader)
            except Exception as exc:
                raise ValueError(f"data 不是合法 CSV:{exc}") from exc
        imported, skipped, overwritten = 0, 0, 0
        for rec in records:
            if not isinstance(rec, dict):
                skipped += 1
                continue
            text = (rec.get("content") or "").strip()
            if not text:
                skipped += 1
                continue
            orig_id = rec.get("id", "")
            mem_id = str(uuid.uuid4()) if new_ids or not orig_id else orig_id
            exists = bool(self._col().get(ids=[mem_id])["ids"]) if orig_id else False
            if exists and not overwrite:
                skipped += 1
                continue
            meta: dict = {}
            meta["created_at"] = _to_float(rec.get("created_at")) or time.time()
            if updated := _to_float(rec.get("updated_at")):
                meta["updated_at"] = updated
            if expires := _to_float(rec.get("expires_at")):
                meta["expires_at"] = expires
            tags_val = rec.get("tags", "")
            if isinstance(tags_val, list):
                tags_val = ",".join(str(t) for t in tags_val)
            meta["tags"] = str(tags_val).strip()
            for key in SCOPE_KEYS:
                if val := rec.get(key):
                    meta[key] = val
            user_md = rec.get("metadata")
            if isinstance(user_md, str) and user_md:
                try:
                    user_md = json.loads(user_md)
                except json.JSONDecodeError:
                    user_md = {}
            if isinstance(user_md, dict):
                for k, v in user_md.items():
                    meta[f"{MD_PREFIX}{k}"] = coerce_scalar(v)
            if exists:
                self._col().update(ids=[mem_id], documents=[text], metadatas=[meta])
                overwritten += 1
            else:
                self._col().add(ids=[mem_id], documents=[text], metadatas=[meta])
                imported += 1
        return {"imported": imported, "skipped": skipped, "overwritten": overwritten}

    # ── 内部 ──────────────────────────────────────────────

    def _check_duplicate(self, text: str, scope_clauses: list[dict]) -> dict | None:
        """查同作用域内是否有相似度 ≥0.85 的记忆。"""
        col = self._col()
        if col.count() == 0:
            return None
        res = col.query(
            query_texts=[text],
            n_results=1,
            where=combine(scope_clauses),
        )
        if not res["ids"] or not res["ids"][0]:
            return None
        dist = res["distances"][0][0]
        sim = 1 - dist
        if sim < DEDUP_THRESHOLD or is_expired(res["metadatas"][0][0]):
            return None
        dup_id = res["ids"][0][0]
        dup_doc = res["documents"][0][0]
        return {
            "duplicate_id": dup_id,
            "similarity": round(sim, 3),
            "existing_content": dup_doc,
            "hint": (
                f"疑似重复(相似度 {sim:.2f}),未插入。"
                "内容有变化 → 用相同 id 更新该记忆;"
                "已足够 → 跳过;确需新增 → 重试并设 force=True。"
            ),
        }


def _to_float(v):
    """尝试把 CSV/JSON 里的时间戳转 float。"""
    if v in (None, "", "null"):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None