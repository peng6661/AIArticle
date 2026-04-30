#!/usr/bin/env python3
"""
init_db.py — MySQL 数据库初始化脚本
────────────────────────────────────────────────────────────────────────────
功能：
  1. 读取 config.yaml（或环境变量）获取 MySQL 连接信息
  2. [可选] 自动创建 MySQL 数据库 Schema（若不存在）
  3. 导入所有 ORM 模型，调用 Base.metadata.create_all() 建表
     · 已存在的表不会被重建或清空（幂等操作）
  4. [可选] 重置：先 DROP 所有表再重建（仅限开发环境）
  5. [可选] 仅做连通性检查，不执行任何 DDL

用法：
  python init_db.py                   # 建表（数据库须已存在）
  python init_db.py --create-db       # 先自动创建数据库 Schema，再建表
  python init_db.py --check           # 仅测试 MySQL 连接，不建表
  python init_db.py --drop-all        # ⚠ 危险：删除所有表再重建（开发环境用）
  python init_db.py --create-db -q    # 静默模式，适合 CI/CD

安装依赖：
  pip install sqlalchemy pymysql pyyaml
────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# ── 将项目根目录加入 sys.path，确保 app.* 可被导入 ──────────────────────────
ROOT = Path(__file__).parent.resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ── 导入顺序很重要：先 database（注册 Base），再导入所有 models ────────────────
from app.db.database import Base, engine, check_db_connection   # noqa: E402
from app.core.config import get_settings                        # noqa: E402

# 显式导入所有 ORM 模型，使其 __tablename__ 注册到 Base.metadata
# 新增模型时，在此处增加 import 即可
from app.db.models import (                                     # noqa: E402, F401
    PipelineJobModel,
    PipelineStepModel,
    WechatImageAssetModel,
)


# ══════════════════════════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════════════════════════

def _mask_url(url: str) -> str:
    """隐藏 URL 中的密码，安全打印日志。"""
    return re.sub(r"(?<=://)([^:]+):([^@]+)@", r"\1:****@", url)


def _print_registered_tables() -> None:
    """打印 Base.metadata 中已注册的所有表名。"""
    tables = sorted(Base.metadata.tables.keys())
    print(f"\n  已注册 {len(tables)} 张表：")
    for t in tables:
        cols = len(Base.metadata.tables[t].columns)
        print(f"    · {t:<30} ({cols} 列)")


# ══════════════════════════════════════════════════════════════════════════════
# Step 0：自动创建 MySQL 数据库 Schema（--create-db 时执行）
# ══════════════════════════════════════════════════════════════════════════════

def create_mysql_schema(verbose: bool = True) -> bool:
    """
    使用不带数据库名的连接连到 MySQL Server，
    执行 CREATE DATABASE IF NOT EXISTS ... CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci。

    返回 True 表示成功，False 表示失败。
    """
    try:
        import pymysql
    except ImportError:
        print("  ❌  未找到 pymysql，请先执行：pip install pymysql")
        return False

    cfg = get_settings()
    host     = cfg.mysql_host
    port     = cfg.mysql_port
    user     = cfg.mysql_user
    password = cfg.mysql_password
    database = cfg.mysql_database
    charset  = cfg.mysql_charset
    collation = cfg.mysql_collation

    if verbose:
        print(f"\n  正在连接 MySQL Server：{user}:****@{host}:{port}")

    try:
        # 不指定 db 参数，连接到 MySQL Server 本身
        conn = pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            charset=charset,
            connect_timeout=10,
        )
        with conn:
            with conn.cursor() as cursor:
                sql = (
                    f"CREATE DATABASE IF NOT EXISTS `{database}` "
                    f"CHARACTER SET {charset} "
                    f"COLLATE {collation};"
                )
                cursor.execute(sql)
                conn.commit()
        if verbose:
            print(f"  ✅  数据库 `{database}` 已就绪（若已存在则跳过创建）")
        return True
    except Exception as exc:
        print(f"  ❌  创建数据库失败：{exc}")
        print("      请检查 MySQL 用户权限：GRANT CREATE ON *.* TO 'user'@'host';")
        return False


# ══════════════════════════════════════════════════════════════════════════════
# Step 1：建表
# ══════════════════════════════════════════════════════════════════════════════

def create_all_tables(verbose: bool = True) -> None:
    """
    在 MySQL 中创建所有尚未存在的数据表（幂等）。
    已存在的表会被跳过，不修改、不清空。
    """
    if verbose:
        _print_registered_tables()
        print(f"\n  正在连接：{_mask_url(get_settings().db_url)}")

    Base.metadata.create_all(bind=engine, checkfirst=True)

    if verbose:
        print("  ✅  所有数据表创建完成（已存在的表已跳过）\n")


# ══════════════════════════════════════════════════════════════════════════════
# 可选：删除所有表（--drop-all，开发环境重置用）
# ══════════════════════════════════════════════════════════════════════════════

def drop_all_tables(verbose: bool = True) -> None:
    """
    ⚠ 危险：删除数据库中 Base.metadata 管理的所有表（含全部数据）。
    仅用于开发 / 测试环境。生产环境严禁使用。
    """
    if verbose:
        _print_registered_tables()
        print("\n  ⚠  即将删除以上所有表及其所有数据，操作不可恢复！")
        confirm = input("  请输入大写 YES 确认：").strip()
        if confirm != "YES":
            print("  已取消，未做任何修改。")
            return

    # MySQL 外键约束需临时关闭才能 DROP 有依赖的表
    with engine.connect() as conn:
        conn.execute(__import__("sqlalchemy").text("SET FOREIGN_KEY_CHECKS = 0;"))
        conn.commit()

    Base.metadata.drop_all(bind=engine)

    with engine.connect() as conn:
        conn.execute(__import__("sqlalchemy").text("SET FOREIGN_KEY_CHECKS = 1;"))
        conn.commit()

    if verbose:
        print("  🗑  所有表已删除。\n")


# ══════════════════════════════════════════════════════════════════════════════
# 仅连通性检查（--check）
# ══════════════════════════════════════════════════════════════════════════════

def check_only(verbose: bool = True) -> int:
    """
    仅测试 MySQL 连通性，不执行任何 DDL。
    返回 0 表示正常，1 表示失败。
    """
    cfg = get_settings()
    if verbose:
        print(f"\n  MySQL URL：{_mask_url(cfg.db_url)}")

    if check_db_connection():
        if verbose:
            print("  ✅  MySQL 连接正常\n")
        return 0
    else:
        if verbose:
            print("  ❌  MySQL 连接失败，请检查以下配置：")
            print(f"       host     = {cfg.mysql_host}")
            print(f"       port     = {cfg.mysql_port}")
            print(f"       user     = {cfg.mysql_user}")
            print(f"       database = {cfg.mysql_database}")
            print("      或通过环境变量 DATABASE_URL / MYSQL_PASSWORD 覆盖\n")
        return 1


# ══════════════════════════════════════════════════════════════════════════════
# CLI 入口
# ══════════════════════════════════════════════════════════════════════════════

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="init_db.py",
        description="AIcreator MySQL 数据库初始化工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python init_db.py                     # 直接建表（数据库须已存在）
  python init_db.py --create-db         # 自动创建数据库 Schema 后再建表
  python init_db.py --check             # 仅测试 MySQL 连接
  python init_db.py --drop-all          # ⚠ 删除所有表再重建（开发环境）
  python init_db.py --create-db -q      # 静默模式，适合 CI/CD 脚本

环境变量（优先级高于 config.yaml）：
  DATABASE_URL    完整的数据库连接 URL
  MYSQL_PASSWORD  MySQL 密码（仅用于 --create-db 建库阶段）
        """,
    )
    parser.add_argument(
        "--create-db",
        action="store_true",
        default=False,
        help="自动在 MySQL Server 中创建目标数据库 Schema（IF NOT EXISTS），再建表",
    )
    parser.add_argument(
        "--drop-all",
        action="store_true",
        default=False,
        help="⚠ 危险：先删除 Base.metadata 管理的所有表再重建（仅限开发环境）",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        default=False,
        help="仅检查 MySQL 连通性，不执行任何建表操作",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        default=False,
        help="静默模式，减少输出（适合 CI/CD 流水线）",
    )
    return parser.parse_args()


def main() -> int:
    args  = _parse_args()
    verbose = not args.quiet

    if verbose:
        print("=" * 60)
        print("  AIcreator  MySQL 数据库初始化")
        print("=" * 60)

    # ── 仅连通性检查，提前退出 ────────────────────────────────────────────────
    if args.check:
        return check_only(verbose=verbose)

    # ── Step 0：自动创建数据库 Schema（可选）─────────────────────────────────
    if args.create_db:
        if verbose:
            print("\n【Step 0】自动创建 MySQL 数据库 Schema")
        if not create_mysql_schema(verbose=verbose):
            return 1

    # ── Step 1：检查 MySQL 连通性（连接到目标数据库）─────────────────────────
    if verbose:
        cfg = get_settings()
        print(f"\n【Step 1】验证 MySQL 连接")
        print(f"  URL：{_mask_url(cfg.db_url)}")

    if not check_db_connection():
        print(
            "\n  ❌  无法连接到 MySQL 数据库，请检查：\n"
            "       1. MySQL 服务是否已启动\n"
            "       2. config.yaml database.url 中的用户名 / 密码 / 主机是否正确\n"
            "       3. 目标数据库是否已存在（未存在请加 --create-db 参数）\n"
            "       4. 用户是否具有对应数据库的权限\n"
        )
        return 1

    if verbose:
        print("  ✅  MySQL 连接正常")

    # ── Step 2：可选 DROP 所有表（仅开发环境）────────────────────────────────
    if args.drop_all:
        if verbose:
            print("\n【Step 2】删除所有已有表")
        drop_all_tables(verbose=verbose)

    # ── Step 3：创建所有表 ────────────────────────────────────────────────────
    if verbose:
        print("\n【Step 3】创建数据表")
    try:
        create_all_tables(verbose=verbose)
    except Exception as exc:
        print(f"  ❌  建表失败：{exc}\n")
        return 1

    if verbose:
        print("=" * 60)
        print("  初始化完成！")
        print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
