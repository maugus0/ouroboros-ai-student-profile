"""Data-access layer for the llm_call_logs table (raw SQL, aiomysql)."""

from typing import Any

from app.core.logging import get_logger
from app.repositories.mysql_base import MySQLBaseRepository
from app.utils.helpers import generate_uuid

logger = get_logger(__name__)


class LLMCallLogRepository(MySQLBaseRepository):
    """CRUD operations on the ``llm_call_logs`` table."""

    async def create_log(self, log_data: dict[str, Any]) -> str:
        """Insert an LLM call log record and return its UUID."""
        log_id = generate_uuid()
        query = """
            INSERT INTO llm_call_logs (
                id, profile_id, operation, llm_provider, model_name,
                input_tokens, output_tokens, total_cost_usd, latency_ms,
                success, error_message, retry_count, trace_id,
                prompt_template_version
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        params = (
            log_id,
            log_data.get('profile_id'),
            log_data['operation'],
            log_data['llm_provider'],
            log_data['model_name'],
            log_data.get('input_tokens'),
            log_data.get('output_tokens'),
            log_data.get('total_cost_usd'),
            log_data.get('latency_ms'),
            log_data.get('success', False),
            log_data.get('error_message'),
            log_data.get('retry_count', 0),
            log_data.get('trace_id', ''),
            log_data.get('prompt_template_version'),
        )
        await self.execute_write(query, params)
        logger.info('llm_call_logged', log_id=log_id, operation=log_data['operation'], provider=log_data['llm_provider'])
        return log_id
