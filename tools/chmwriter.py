"""
chmwriter.py - 纯 Python 的 CHM (Compiled HTML Help) 打包器

在 macOS / Linux 上生成 .chm，无需 Microsoft HTML Help Workshop。

实现范围：
  * ITSF / ITSP / PMGL / PMGI 目录块（未压缩 section 0）
  * /#SYSTEM 系统文件
  * 二进制目录树：/#TOCIDX、/#TOPICS、/#STRINGS、/#URLTBL、/#URLSTR
    （这是 hh.exe 显示左侧目录树的必要条件，纯 .hhc 不会被 hh.exe 读取）

二进制布局参考：
  - chmlib (jedwing/CHMLib) src/chm_lib.c  —— ITSF/ITSP/PMGL 头部字段与顺序
  - Free Pascal packages/chm/src/*.pas     —— #SYSTEM 记录流与二进制 TOC 语义
"""

from __future__ import annotations

import struct
import uuid
from dataclasses import dataclass, field
from typing import Iterable

BLOCK_SIZE = 0x1000
LANG_ENGLISH = 0x0409
LANG_CHINESE = 0x0804

# 编码说明：hh.exe 的二进制 TOC 字符串（#STRINGS/#SYSTEM）按系统活动代码页
# (ACP) 解码。简体中文 Windows 的 ACP 是 CP936(GBK)，因此中文标题必须以
# GBK 字节写入；正文 HTML 仍是 UTF-8 + <meta charset>，由 IE 引擎按 meta 识别。
TOC_TEXT_ENCODING = "gbk"

ITSF_GUID = uuid.UUID("{7C01FD10-7BAA-11D0-9E0C-00A0C922E6EC}")
ITSF_STREAM_GUID = uuid.UUID("{7C01FD11-7BAA-11D0-9E0C-00A0C922E6EC}")
ITSP_GUID = uuid.UUID("{5D02926A-212E-11D0-9DF9-00A0C922E6EC}")

TOC_HAS_CHILDREN = 4
TOC_HAS_LOCAL = 8


# --------------------------------------------------------------------------
# 基础编码工具
# --------------------------------------------------------------------------

def enc_int(value: int) -> bytes:
    """CHM 的 7-bit 变长整数（高位在前，非末字节置 0x80）。"""
    if value == 0:
        return b"\x00"
    groups = []
    while value:
        groups.append(value & 0x7F)
        value >>= 7
    groups.reverse()
    out = bytearray()
    for i, g in enumerate(groups):
        out.append(g | (0x80 if i != len(groups) - 1 else 0))
    return bytes(out)


def _u16(v: int) -> bytes:
    return struct.pack("<H", v & 0xFFFF)


def _u32(v: int) -> bytes:
    return struct.pack("<I", v & 0xFFFFFFFF)


def _i32(v: int) -> bytes:
    return struct.pack("<i", v)


def _u64(v: int) -> bytes:
    return struct.pack("<Q", v & 0xFFFFFFFFFFFFFFFF)


# --------------------------------------------------------------------------
# 目录树节点
# --------------------------------------------------------------------------

@dataclass
class TocNode:
    title: str
    local: str = ""          # CHM 内部路径，如 "index.html"（不带前导 /）
    children: list = field(default_factory=list)

    def add(self, node: "TocNode") -> "TocNode":
        self.children.append(node)
        return node


# --------------------------------------------------------------------------
# 字符串 / URL 池（供二进制 TOC 使用）
# --------------------------------------------------------------------------

class StringPool:
    """/#STRINGS：以 NUL 结尾的字符串池，条目不可跨 0x1000 边界。"""

    def __init__(self) -> None:
        self.buf = bytearray()
        self.index: dict[str, int] = {}

    def add(self, s: str) -> int:
        if s in self.index:
            return self.index[s]
        if not self.buf:
            self.buf.append(0)  # #STRINGS 以 NUL 开头
        data = s.encode(TOC_TEXT_ENCODING, "replace")
        pos = len(self.buf)
        next_block = (pos & 0xFFFFF000) + 0x1000
        if pos + len(data) + 1 > next_block:
            self.buf.extend(b"\x00" * (next_block - pos))
            pos = next_block
        offset = pos
        self.buf.extend(data)
        self.buf.append(0)
        self.index[s] = offset
        return offset


class UrlPool:
    """/#URLSTR + /#URLTBL：URL 字符串池与按 hash 排序的索引表。"""

    def __init__(self) -> None:
        self.urlstr = bytearray()
        self.entries: list[tuple[int, int, int]] = []  # (hash, topic_index, url_offset)
        self._url_index: dict[str, int] = {}

    @staticmethod
    def hash_url(url: str) -> int:
        h = 0
        for ch in url.encode("utf-8", "replace"):
            if ch > ord("Z"):
                ch -= ord("a") - ord("A")
            h = (h * 43 + (ch - ord("0"))) & 0xFFFFFFFF
        return h

    def _add_urlstr(self, url: str) -> int:
        data = url.encode("utf-8", "replace")
        need = 9 + len(data)
        rem = 0x4000 - (len(self.urlstr) % 0x4000)
        if rem < need:
            self.urlstr.extend(b"\x00" * rem)
        if len(self.urlstr) % 0x4000 == 0:
            self.urlstr.append(0)
        offset = len(self.urlstr)
        self.urlstr.extend(_u32(0))  # "Local" 之后的 URL 偏移
        self.urlstr.extend(_u32(0))  # FrameName 偏移
        self.urlstr.extend(data)
        self.urlstr.append(0)
        return offset

    def add(self, url: str, topic_index: int) -> int:
        """返回 #URLTBL 的条目序号，稍后由 build() 回填为真实偏移。"""
        if url.startswith("/"):
            url = url[1:]
        if url not in self._url_index:
            self._url_index[url] = self._add_urlstr(url)
        self.entries.append((self.hash_url(url), topic_index, self._url_index[url]))
        return len(self.entries) - 1

    def build(self) -> tuple[bytes, dict[int, int]]:
        """按 hash 排序生成 #URLTBL，返回 (数据, 序号->偏移 映射)。"""
        order = sorted(range(len(self.entries)), key=lambda i: self.entries[i][0])
        buf = bytearray()
        offsets: dict[int, int] = {}
        for src_pos, i in enumerate(order):
            h, topic, url_off = self.entries[i]
            if len(buf) & 0xFFC == 0xFFC:  # 不跨 0x1000 块
                buf.extend(_u32(0))
            offsets[src_pos] = len(buf)
            buf.extend(_u32(h))
            buf.extend(_u32(topic))
            buf.extend(_u32(url_off))
        return bytes(buf), offsets


# --------------------------------------------------------------------------
# 二进制目录树（#TOCIDX / #TOPICS）
# --------------------------------------------------------------------------

class BinaryToc:
    HEADER_SIZE = 0x1000
    ENTRY_MAGIC = 0x29A  # 首个 TTocEntry.IncrementedInt，与 FPC 实现保持一致

    def __init__(self) -> None:
        self.strings = StringPool()
        self.urls = UrlPool()
        self.topics: list[bytearray] = []  # 每条 16 字节
        self._nodes: list[dict] = []

    def build(self, roots: Iterable[TocNode]) -> tuple[bytes, bytes]:
        """返回 (#TOCIDX, #TOPICS)。

        EntryInfo 必须按深度优先（DFS）顺序写入：子节点紧跟父节点。
        大量第三方 CHM 阅读器依赖"线性顺序 + 父指针"恢复层级，
        广度优先（BFS）布局会被平铺成一级列表。
        """
        # 第一遍：深度优先展开，为每个节点预分配 EntryInfo 位置
        flat: list[dict] = []

        def walk(node: TocNode, parent_slot: int) -> None:
            slot = len(flat)
            flat.append(
                {
                    "node": node,
                    "size": 28 if node.children else 20,
                    "parent": parent_slot,
                    "sibling": -1,
                    "first_child": -1,
                    "entry_num": None,
                }
            )
            if parent_slot >= 0 and flat[parent_slot]["first_child"] < 0:
                flat[parent_slot]["first_child"] = slot
            for child in node.children:
                walk(child, slot)

        for root in roots:
            walk(root, -1)

        # 计算每个节点在 EntryInfo 流中的绝对偏移（4KB 头部之后）
        offset = self.HEADER_SIZE
        for item in flat:
            item["offset"] = offset
            offset += item["size"]

        # 同一层的兄弟节点串联
        prev_by_parent: dict[int, int] = {}
        for slot, item in enumerate(flat):
            p = item["parent"]
            if p in prev_by_parent:
                flat[prev_by_parent[p]]["sibling"] = slot
            prev_by_parent[p] = slot

        # 第二遍：写入 EntryInfo / TopicOffset / Entry 三条流
        entry_info = bytearray()
        topic_offsets = bytearray()
        entries = bytearray()
        entry_count = self.ENTRY_MAGIC

        for item in flat:
            node: TocNode = item["node"]
            props = 0
            if node.children:
                props |= TOC_HAS_CHILDREN
            if node.local:
                props |= TOC_HAS_LOCAL

            topic_index = 0
            if props & TOC_HAS_LOCAL:
                topic_index = len(self.topics)
                url_ref = self.urls.add(node.local, topic_index)
                self.topics.append(
                    bytearray(
                        _u32(item["offset"])
                        + _u32(self.strings.add(node.title))
                        + _u32(url_ref)  # 占位，稍后回填真实偏移
                        + _u16(2)  # InContents
                        + _u16(0)
                    )
                )
                topic_offset_pos = len(topic_offsets)
                topic_offsets.extend(_u32(topic_index))
                entries.extend(
                    _u32(item["offset"])
                    + _u32(entry_count)
                    + _u32(topic_offset_pos)
                    + _u32(topic_index)
                )
                item["entry_num"] = entry_count
                entry_count += 1
                topics_or_strings = topic_index
            else:
                topics_or_strings = self.strings.add(node.title)

            entry_info.extend(_u16(0))  # Unknown1
            entry_info.extend(_u16(entry_count - self.ENTRY_MAGIC))  # EntryIndex
            entry_info.extend(_u32(props))
            entry_info.extend(_u32(topics_or_strings))
            entry_info.extend(_u32(flat[item["parent"]]["offset"] if item["parent"] >= 0 else 0))
            entry_info.extend(_u32(flat[item["sibling"]]["offset"] if item["sibling"] >= 0 else 0))
            if props & TOC_HAS_CHILDREN:
                entry_info.extend(
                    _u32(flat[item["first_child"]]["offset"] if item["first_child"] >= 0 else 0)
                )
                entry_info.extend(_u32(0))  # Unknown3

        # 回填 #TOPICS 里的 URLTableOffset
        urltbl, url_offsets = self.urls.build()
        for i, topic in enumerate(self.topics):
            ref = struct.unpack_from("<I", topic, 8)[0]
            struct.pack_into("<I", topic, 8, url_offsets.get(ref, 0))

        header = bytearray(self.HEADER_SIZE)
        struct.pack_into("<I", header, 0, BLOCK_SIZE)
        struct.pack_into("<I", header, 4, self.HEADER_SIZE + len(entry_info) + len(topic_offsets))
        struct.pack_into("<I", header, 8, entry_count - self.ENTRY_MAGIC)
        struct.pack_into("<I", header, 12, self.HEADER_SIZE + len(entry_info))

        tocidx = bytes(header) + bytes(entry_info) + bytes(topic_offsets) + bytes(entries)
        topics = b"".join(bytes(t) for t in self.topics)
        self._urltbl = urltbl
        self._urlstr = bytes(self.urls.urlstr)
        return tocidx, topics

    @property
    def urltbl(self) -> bytes:
        return getattr(self, "_urltbl", b"")

    @property
    def urlstr(self) -> bytes:
        return getattr(self, "_urlstr", b"")

    @property
    def strings_blob(self) -> bytes:
        return bytes(self.strings.buf) or b"\x00"


# --------------------------------------------------------------------------
# CHM 打包器
# --------------------------------------------------------------------------

class ChmWriter:
    def __init__(
        self,
        title: str = "Documentation",
        default_page: str = "index.html",
        language_id: int = LANG_ENGLISH,
        default_font: str = "",
        toc_name: str = "toc.hhc",
        index_name: str = "",
        include_binary_toc: bool = False,
    ) -> None:
        self.title = title
        self.default_page = default_page
        self.language_id = language_id
        self.default_font = default_font
        self.toc_name = toc_name
        self.index_name = index_name
        # True 时写入二进制目录树（/#TOCIDX 等五个文件）。
        # hh.exe 原生支持，但部分第三方阅读器会把全部条目平铺成一级列表，
        # 因此默认关闭，仅携带 toc.hhc（层级正确的目录源）。
        self.include_binary_toc = include_binary_toc
        self.files: list[tuple[str, bytes]] = []   # ("/path/in/chm", data)
        self.toc: list[TocNode] = []

    # -- 内容收集 ---------------------------------------------------------

    def add_file(self, name: str, data: bytes) -> None:
        name = name.replace("\\", "/")
        if not name.startswith("/"):
            name = "/" + name
        self.files.append((name, data))

    def add_toc(self, node: TocNode) -> None:
        self.toc.append(node)

    # -- #SYSTEM ----------------------------------------------------------

    def _system_file(self) -> bytes:
        """记录式 /#SYSTEM（与 FPC chmwriter 相同的语义）。"""
        out = bytearray()
        out.extend(_u32(3))  # version

        def rec(code: int, payload: bytes) -> None:
            out.extend(_u16(code))
            out.extend(_u16(len(payload)))
            out.extend(payload)

        def rec_str(code: int, text: str) -> None:
            data = text.encode(TOC_TEXT_ENCODING, "replace") + b"\x00"
            rec(code, data)

        import time

        # 10: 时间戳（毫秒）
        rec(10, _u32(int(time.time() * 1000) % (1 << 32)))
        # 9: 编译器版本串
        rec_str(9, "HHA Version 4.74.8702")
        # 4: 搜索/链接开关结构（36 字节）
        rec(
            4,
            _u32(self.language_id)
            + _u32(0)
            + _u32(0)   # 0 = 关闭全文搜索
            + _u32(0)   # klinks
            + _u32(0)   # alinks
            + _u32(0)
            + _u32(0)
            + _u32(0)
            + _u32(0),
        )
        rec_str(2, self.default_page)   # 默认页
        rec_str(3, self.title)          # 标题
        if self.default_font:
            rec_str(16, self.default_font)
        if self.toc_name:
            rec_str(0, self.toc_name)   # 目录文件（供第三方阅读器使用）
        if self.index_name:
            rec_str(1, self.index_name)
        rec(11, _u32(0))                # 11: 存在二进制 TOC
        return bytes(out)

    # -- 目录块 -----------------------------------------------------------

    def _build_directory(self, entries: list[tuple[str, int, int, int]]) -> bytes:
        """entries: (name, section, offset, length)，返回 ITSP + 块序列。"""
        chunks: list[bytes] = []

        # --- PMGL ---
        pmgl_index: list[list[tuple[str, int, int, int]]] = [[]]
        for entry in entries:
            size = len(enc_int(len(entry[0]))) + len(entry[0]) + len(enc_int(entry[1])) \
                + len(enc_int(entry[2])) + len(enc_int(entry[3]))
            # 预留 quickref：每 4 个条目 2 字节 + 2 字节计数
            cur = pmgl_index[-1]
            used = 20 + sum(self._entry_size(e) for e in cur) + size
            quickref = 2 * ((len(cur) + 1 + 3) // 4) + 2
            if used + quickref > BLOCK_SIZE and cur:
                pmgl_index.append([entry])
            else:
                cur.append(entry)

        # 始终生成一层 PMGI 索引块，与 HTML Help Workshop 的习惯一致
        pmgi_chunks: list[bytes] = []
        pmgi_items = []
        for i, chunk_entries in enumerate(pmgl_index):
            pmgi_items.append((chunk_entries[0][0], i))
        pmgi_chunks.append(self._pmgi_chunk(pmgi_items))

        for i, chunk_entries in enumerate(pmgl_index):
            chunks.append(self._pmgl_chunk(chunk_entries, i, len(pmgl_index)))

        all_chunks = chunks + pmgi_chunks
        index_root = len(chunks)          # PMGI 块位于 PMGL 之后
        index_depth = 2

        itsp = bytearray()
        itsp.extend(b"ITSP")
        itsp.extend(_u32(1))                      # version
        itsp.extend(_u32(0x54))                   # header length
        itsp.extend(_u32(0x0A))                   # unknown
        itsp.extend(_u32(BLOCK_SIZE))             # block length
        itsp.extend(_u32(2))                      # density / blockidx interval
        itsp.extend(_u32(index_depth))            # index depth
        itsp.extend(_u32(index_root & 0xFFFFFFFF))
        itsp.extend(_u32(0))                         # 首个 PMGL 块
        itsp.extend(_u32(len(pmgl_index) - 1))       # 最后一个 PMGL 块
        itsp.extend(_u32(0xFFFFFFFF))                # unknown
        itsp.extend(_u32(len(all_chunks)))           # 目录块总数
        itsp.extend(_u32(self.language_id))
        itsp.extend(ITSP_GUID.bytes_le)
        itsp.extend(_u32(0x54))                      # 头部长度（再次）
        itsp.extend(_i32(-1))
        itsp.extend(_i32(-1))
        itsp.extend(_i32(-1))
        assert len(itsp) == 0x54
        return bytes(itsp) + b"".join(all_chunks)

    @staticmethod
    def _entry_size(entry: tuple[str, int, int, int]) -> int:
        name = entry[0]
        return (
            len(enc_int(len(name)))
            + len(name)
            + len(enc_int(entry[1]))
            + len(enc_int(entry[2]))
            + len(enc_int(entry[3]))
        )

    def _pmgl_chunk(
        self, entries: list[tuple[str, int, int, int]], index: int, total: int
    ) -> bytes:
        body = bytearray()
        offsets: list[int] = []
        for name, section, offset, length in entries:
            offsets.append(20 + len(body))
            body.extend(enc_int(len(name)))
            body.extend(name.encode("utf-8"))
            body.extend(enc_int(section))
            body.extend(enc_int(offset))
            body.extend(enc_int(length))

        # quickref 区：块末尾，每 4 个条目一个 WORD 偏移，最后 2 字节为条目数
        nqr = (len(entries) + 3) // 4
        quickref_len = 2 * nqr + 2
        quickref = bytearray(quickref_len)
        struct.pack_into("<H", quickref, quickref_len - 2, len(entries))
        for i in range(nqr):
            struct.pack_into("<H", quickref, quickref_len - 4 - 2 * i, offsets[i * 4])

        header = bytearray()
        header.extend(b"PMGL")
        # free space 必须包含末尾的 quickref 区，阅读器据此推算条目区边界
        header.extend(_u32(BLOCK_SIZE - 20 - len(body)))
        header.extend(_u32(0))
        header.extend(_i32(index - 1 if index > 0 else -1))
        header.extend(_i32(index + 1 if index < total - 1 else -1))

        chunk = bytearray(BLOCK_SIZE)
        chunk[0:20] = header
        chunk[20:20 + len(body)] = body
        chunk[BLOCK_SIZE - quickref_len:BLOCK_SIZE] = quickref
        return bytes(chunk)

    def _pmgi_chunk(self, items: list[tuple[str, int]]) -> bytes:
        body = bytearray()
        offsets: list[int] = []
        for name, block in items:
            offsets.append(8 + len(body))
            body.extend(enc_int(len(name)))
            body.extend(name.encode("utf-8"))
            body.extend(enc_int(block))

        nqr = (len(items) + 3) // 4
        quickref_len = 2 * nqr + 2
        quickref = bytearray(quickref_len)
        struct.pack_into("<H", quickref, quickref_len - 2, len(items))
        for i in range(nqr):
            struct.pack_into("<H", quickref, quickref_len - 4 - 2 * i, offsets[i * 4])

        header = bytearray()
        header.extend(b"PMGI")
        header.extend(_u32(BLOCK_SIZE - 8 - len(body)))

        chunk = bytearray(BLOCK_SIZE)
        chunk[0:8] = header
        chunk[8:8 + len(body)] = body
        chunk[BLOCK_SIZE - quickref_len:BLOCK_SIZE] = quickref
        return bytes(chunk)

    # -- 写出 -------------------------------------------------------------

    def write(self, path: str) -> None:
        """写出未压缩 CHM（微软格式允许的合法形态，兼容性最好）。"""
        prepared: list[tuple[str, bytes]] = []
        if self.include_binary_toc:
            prepared.extend(self._collect_toc_files())
        prepared.append(("/#SYSTEM", self._system_file()))
        # DataSpace 属于系统项，按规范不带前导 "/"
        prepared.append(("::DataSpace/NameList", self._name_list()))
        prepared.extend(self.files)

        entries: list[tuple[str, int, int, int]] = []
        payload = bytearray()
        for name, data in prepared:
            entries.append((name, 0, len(payload), len(data)))
            payload.extend(data)
            while len(payload) % 8:
                payload.append(0)
        entries.append(("::DataSpace/Storage/Uncompressed/Content", 0, 0, len(payload)))

        entries.sort(key=lambda e: e[0].lower())
        directory = self._build_directory(entries)

        itsf_len = 0x60
        section0_prefix_len = 0x18
        data_offset = itsf_len + section0_prefix_len   # 文件内容的绝对基址
        section0_offset = itsf_len
        section0_len = section0_prefix_len + len(payload)
        dir_offset = section0_offset + section0_len
        file_size = dir_offset + len(directory)

        section0 = (
            _u32(0x01FE)            # 固定标识
            + _u32(0)
            + _u64(file_size)       # 整个 CHM 文件大小
            + _u32(0)
            + _u32(0)
            + bytes(payload)
        )

        itsf = bytearray()
        itsf.extend(b"ITSF")
        itsf.extend(_u32(3))
        itsf.extend(_u32(0x60))
        itsf.extend(_u32(1))
        itsf.extend(_u32(0))  # timestamp
        itsf.extend(_u32(self.language_id))
        itsf.extend(ITSF_GUID.bytes_le)
        itsf.extend(ITSF_STREAM_GUID.bytes_le)
        itsf.extend(_u64(section0_offset))
        itsf.extend(_u64(section0_len))
        itsf.extend(_u64(dir_offset))
        itsf.extend(_u64(len(directory)))
        itsf.extend(_u64(data_offset))
        assert len(itsf) == 0x60

        with open(path, "wb") as fh:
            fh.write(bytes(itsf))
            fh.write(section0)
            fh.write(directory)

    def _collect_toc_files(self) -> list[tuple[str, bytes]]:
        binary_toc = BinaryToc() if self.toc else None
        prepared: list[tuple[str, bytes]] = []
        if binary_toc:
            tocidx, topics = binary_toc.build(self.toc)
            prepared.append(("/#TOCIDX", tocidx))
            prepared.append(("/#TOPICS", topics))
            prepared.append(("/#STRINGS", binary_toc.strings_blob))
            if binary_toc.urlstr:
                prepared.append(("/#URLSTR", binary_toc.urlstr))
            if binary_toc.urltbl:
                prepared.append(("/#URLTBL", binary_toc.urltbl))
        return prepared

    @staticmethod
    def _name_list() -> bytes:
        """::DataSpace/NameList：仅声明 Uncompressed 存储。"""
        out = bytearray()
        out.extend(_u16(16))  # 以 WORD 为单位的总长度
        out.extend(_u16(1))   # 条目数
        out.extend(_u16(12))  # 名称字符数（不含结尾 NUL）
        out.extend("Uncompressed\0".encode("utf-16-le"))
        return bytes(out)


# --------------------------------------------------------------------------
# 只读校验器：把生成的 CHM 解析回来，确认结构自洽
# --------------------------------------------------------------------------

class ChmReader:
    def __init__(self, path: str) -> None:
        with open(path, "rb") as fh:
            self.data = fh.read()
        self._parse()

    def _parse(self) -> None:
        d = self.data
        assert d[0:4] == b"ITSF", "不是合法的 CHM 文件"
        self.version = struct.unpack_from("<I", d, 4)[0]
        self.dir_offset = struct.unpack_from("<Q", d, 0x48)[0]
        self.dir_len = struct.unpack_from("<Q", d, 0x50)[0]
        self.data_offset = struct.unpack_from("<Q", d, 0x58)[0]

        assert d[self.dir_offset:self.dir_offset + 4] == b"ITSP", "ITSP 头位置错误"
        p = self.dir_offset
        self.block_len = struct.unpack_from("<I", d, p + 0x10)[0]
        self.index_root = struct.unpack_from("<I", d, p + 0x1C)[0]
        self.num_blocks = struct.unpack_from("<I", d, p + 0x2C)[0]

        self.files: dict[str, tuple[int, int, int]] = {}
        base = self.dir_offset + 0x54
        for b in range(self.num_blocks):
            off = base + b * self.block_len
            if d[off:off + 4] != b"PMGL":
                continue
            # 条目区终点由 free_space 反推：block_end - free_space 之后的
            # 内容是 quickref 区，不能当作条目解析
            free_space = struct.unpack_from("<I", d, off + 4)[0]
            entry_end = off + self.block_len - free_space
            pos = off + 20
            while pos < entry_end:
                name_len, pos = self._read_enc_int(d, pos)
                name = d[pos:pos + name_len].decode("utf-8")
                pos += name_len
                section, pos = self._read_enc_int(d, pos)
                offset, pos = self._read_enc_int(d, pos)
                length, pos = self._read_enc_int(d, pos)
                self.files[name] = (section, offset, length)

    @staticmethod
    def _read_enc_int(d: bytes, pos: int) -> tuple[int, int]:
        value = 0
        while True:
            b = d[pos]
            pos += 1
            value = (value << 7) | (b & 0x7F)
            if not b & 0x80:
                break
        return value, pos

    def read(self, name: str) -> bytes:
        section, offset, length = self.files[name]
        start = self.data_offset + offset
        return self.data[start:start + length]

    def listing(self) -> list[str]:
        return sorted(self.files)
