from neo4j import AsyncGraphDatabase, AsyncDriver


class Neo4jClient:
    def __init__(self, uri: str, user: str, password: str):
        self._driver: AsyncDriver = AsyncGraphDatabase.driver(uri, auth=(user, password))

    async def verify_connectivity(self) -> bool:
        try:
            await self._driver.verify_connectivity()
            return True
        except Exception:
            return False

    async def execute_query(self, cypher: str, params: dict | None = None) -> list[dict]:
        async with self._driver.session() as session:
            result = await session.run(cypher, params or {})
            return [record.data() async for record in result]

    async def execute_write(self, cypher: str, params: dict | None = None) -> None:
        async with self._driver.session() as session:
            await session.run(cypher, params or {})

    async def close(self) -> None:
        await self._driver.close()
