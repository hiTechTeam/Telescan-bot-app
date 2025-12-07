import mimetypes
from aiobotocore.session import get_session, AioBaseClient
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional
from aiogram import Bot

__all__ = ["S3Client"]


class S3Client:
    def __init__(
        self,
        access_key: str,
        secret_key: str,
        endpoint_url: str,
        public_base_url: str,
        bucket_name: str,
    ) -> None:
        self.config = {
            "aws_access_key_id": access_key,
            "aws_secret_access_key": secret_key,
            "endpoint_url": endpoint_url,
        }
        self.public_base_url = public_base_url.rstrip("/")
        self.bucket_name = bucket_name
        self.session = get_session()

    @asynccontextmanager
    async def get_client(self) -> AsyncGenerator[AioBaseClient, None]:
        async with self.session.create_client("s3", **self.config) as client:
            yield client

    async def upload_file(
        self, file_bytes: bytes, object_name: str, content_type: Optional[str] = None
    ) -> str:
        if content_type is None:
            content_type_guess, _ = mimetypes.guess_type(object_name)
            content_type = content_type_guess or "application/octet-stream"

        async with self.get_client() as client:
            await client.put_object(
                Bucket=self.bucket_name,
                Key=object_name,
                Body=file_bytes,
                ContentType=content_type,
                ACL="public-read",
            )  # type: ignore

        return f"{self.public_base_url}/{object_name}"

    async def upload_telegram_photo(
        self, bot: Bot, file_id: str, object_name: str
    ) -> Optional[str]:
        """
        Downloads a Telegram file by file_id and uploads it to S3.
        Returns public URL.
        """

        tg_file = await bot.get_file(file_id)
        file_bytes = await bot.download_file(tg_file.file_path)  # type: ignore

        return await self.upload_file(
            file_bytes=file_bytes.read(),  # type: ignore
            object_name=object_name,
            content_type="image/jpeg",
        )
