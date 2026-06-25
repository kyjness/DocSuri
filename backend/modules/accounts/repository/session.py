import json
from datetime import UTC, datetime

import redis.asyncio as aioredis
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from ..models import SessionRecord, SessionStoreUnavailableException, UserRole


class SessionRepository:
    """
    aioredis (redis.asyncio) 기반의 세션 저장소 (ElastiCache Redis)
    피드백 ② 반영: Redis Connection Pool (최대 50 커넥션, 타임아웃 1초) 명시적 제어 및 Fail-Closed 예외 래핑
    """
    
    def __init__(
        self,
        redis_host: str = "localhost",
        redis_port: int = 6379,
        redis_db: int = 0,
        use_tls: bool = False,
    ):
        # 피드백 ② 반영: max_connections=50 전용 풀. NFR Design(logical-components)에 맞춰
        # socket_timeout/connect 1.0s로 빠른 Fail-Closed (기존 2.0 → 1.0).
        # use_tls: ElastiCache transit_encryption_enabled=True 클러스터는 TLS 필수 →
        # SSLConnection 사용(Amazon CA 기본 검증). 평문 풀로는 핸드셰이크 실패.
        pool_kwargs = {
            "host": redis_host,
            "port": redis_port,
            "db": redis_db,
            "max_connections": 50,
            "socket_timeout": 1.0,
            "socket_connect_timeout": 1.0,
            "decode_responses": True,  # 결과를 string으로 자동 디코딩
        }
        if use_tls:
            pool_kwargs["connection_class"] = aioredis.SSLConnection
        self._pool = aioredis.ConnectionPool(**pool_kwargs)
        self._redis = aioredis.Redis(connection_pool=self._pool)

    def _wrap_exception(self, e: Exception) -> SessionStoreUnavailableException:
        """Redis 커넥션/타임아웃 예외를 Fail-Closed 비즈니스 예외로 래핑합니다."""
        return SessionStoreUnavailableException(f"세션 저장소(Redis)에 연결할 수 없습니다. (Fail-Closed): {str(e)}")

    async def save(self, session: SessionRecord) -> None:
        """세션 정보를 Redis에 영속화합니다. TTL은 absolute 만료 시간 기준으로 자동 세팅됩니다."""
        key = f"session:{session.handle}"
        data = {
            "handle": session.handle,
            "user_id": session.user_id,
            "created_at": session.created_at.isoformat(),
            "last_active_at": session.last_active_at.isoformat(),
            "expires_at": session.expires_at.isoformat(),
            "role": session.role,
            "mfa_verified": session.mfa_verified,
        }
        
        # absolute 만료 일시까지 남은 초 계산 (TTL)
        now = datetime.now(UTC)
        ttl = int((session.expires_at - now).total_seconds())
        if ttl <= 0:
            return

        try:
            # Redis에 저장하면서 TTL 설정
            await self._redis.set(key, json.dumps(data), ex=ttl)
            # 사용자별 세션 핸들 인덱스(전 세션 무효화용 — FR-26/BR-A8). 동일 TTL로 갱신해
            # 자동 정리되게 한다. 인덱스에 남은 만료 핸들은 무효화 시 no-op이라 무해.
            # ponytail: 집합 인덱스 = 사용자당 세션 수가 적다는 전제; 대규모면 핸들 TTL 동기화 필요.
            uset = f"user_sessions:{session.user_id}"
            await self._redis.sadd(uset, session.handle)
            await self._redis.expire(uset, ttl)
        except (RedisConnectionError, RedisTimeoutError) as e:
            raise self._wrap_exception(e) from e
        except Exception as e:
            raise SessionStoreUnavailableException(f"세션 저장 장애: {str(e)}") from e

    async def get(self, handle: str) -> SessionRecord | None:
        """세션 핸들러로 세션을 조회합니다."""
        key = f"session:{handle}"
        try:
            data_str = await self._redis.get(key)
            if not data_str:
                return None
            
            data = json.loads(data_str)
            return SessionRecord(
                handle=data["handle"],
                user_id=data["user_id"],
                created_at=datetime.fromisoformat(data["created_at"]),
                last_active_at=datetime.fromisoformat(data["last_active_at"]),
                expires_at=datetime.fromisoformat(data["expires_at"]),
                role=data.get("role", UserRole.USER.value),  # 구버전 레코드 호환: 누락 시 USER
                mfa_verified=bool(data.get("mfa_verified", False)),  # 누락 시 MFA 미통과로 안전 폴백
            )
        except (RedisConnectionError, RedisTimeoutError) as e:
            raise self._wrap_exception(e) from e
        except Exception as e:
            raise SessionStoreUnavailableException(f"세션 조회 장애: {str(e)}") from e

    async def delete(self, handle: str) -> None:
        """세션 핸들러를 파기합니다."""
        key = f"session:{handle}"
        try:
            await self._redis.delete(key)
        except (RedisConnectionError, RedisTimeoutError) as e:
            raise self._wrap_exception(e) from e
        except Exception as e:
            raise SessionStoreUnavailableException(f"세션 삭제 장애: {str(e)}") from e
            
    async def invalidate_all_for_user(self, user_id: str) -> None:
        """해당 사용자의 모든 활성 세션을 파기합니다 (FR-26/BR-A8 — 재설정 시 전 세션 무효화).
        user_sessions 인덱스 집합을 읽어 각 핸들의 세션 키를 삭제하고 인덱스도 비운다."""
        uset = f"user_sessions:{user_id}"
        try:
            handles = await self._redis.smembers(uset)
            if handles:
                await self._redis.delete(*[f"session:{h}" for h in handles])
            await self._redis.delete(uset)
        except (RedisConnectionError, RedisTimeoutError) as e:
            raise self._wrap_exception(e) from e
        except Exception as e:
            raise SessionStoreUnavailableException(f"세션 일괄 파기 장애: {str(e)}") from e

    async def close(self) -> None:
        """커넥션 풀을 정상 종료합니다. (App shell의 shutdown 이벤트에서 1회 호출)"""
        # redis.asyncio 는 close() 를 aclose() 로 대체(deprecated)했다. 신버전을 우선 사용하고,
        # 구버전(aclose 미존재)에서는 close() 로 폴백한다.
        aclose = getattr(self._redis, "aclose", None)
        if aclose is not None:
            await aclose()
        else:
            await self._redis.close()
        await self._pool.disconnect()
