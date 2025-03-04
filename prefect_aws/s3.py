"""Tasks for interacting with AWS S3"""
import io
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

import boto3
from botocore.paginate import PageIterator
from prefect import get_run_logger, task
from prefect.filesystems import ReadableFileSystem, WritableFileSystem
from prefect.utilities.asyncutils import run_sync_in_worker_thread, sync_compatible
from pydantic import root_validator, validator

from prefect_aws import AwsCredentials, MinIOCredentials
from prefect_aws.client_parameters import AwsClientParameters


@task
async def s3_download(
    bucket: str,
    key: str,
    aws_credentials: AwsCredentials,
    aws_client_parameters: AwsClientParameters = AwsClientParameters(),
) -> bytes:
    """
    Downloads an object with a given key from a given S3 bucket.

    Args:
        bucket: Name of bucket to download object from. Required if a default value was
            not supplied when creating the task.
        key: Key of object to download. Required if a default value was not supplied
            when creating the task.
        aws_credentials: Credentials to use for authentication with AWS.
        aws_client_parameters: Custom parameter for the boto3 client initialization..


    Returns:
        A `bytes` representation of the downloaded object.

    Example:
        Download a file from an S3 bucket:

        ```python
        from prefect import flow
        from prefect_aws import AwsCredentials
        from prefect_aws.s3 import s3_download


        @flow
        async def example_s3_download_flow():
            aws_credentials = AwsCredentials(
                aws_access_key_id="acccess_key_id",
                aws_secret_access_key="secret_access_key"
            )
            data = await s3_download(
                bucket="bucket",
                key="key",
                aws_credentials=aws_credentials,
            )

        example_s3_download_flow()
        ```
    """
    logger = get_run_logger()
    logger.info("Downloading object from bucket %s with key %s", bucket, key)

    s3_client = aws_credentials.get_boto3_session().client(
        "s3", **aws_client_parameters.get_params_override()
    )
    stream = io.BytesIO()
    await run_sync_in_worker_thread(
        s3_client.download_fileobj, Bucket=bucket, Key=key, Fileobj=stream
    )
    stream.seek(0)
    output = stream.read()

    return output


@task
async def s3_upload(
    data: bytes,
    bucket: str,
    aws_credentials: AwsCredentials,
    aws_client_parameters: AwsClientParameters = AwsClientParameters(),
    key: Optional[str] = None,
) -> str:
    """
    Uploads data to an S3 bucket.

    Args:
        data: Bytes representation of data to upload to S3.
        bucket: Name of bucket to upload data to. Required if a default value was not
            supplied when creating the task.
        aws_credentials: Credentials to use for authentication with AWS.
        aws_client_parameters: Custom parameter for the boto3 client initialization..
        key: Key of object to download. Defaults to a UUID string.

    Returns:
        The key of the uploaded object

    Example:
        Read and upload a file to an S3 bucket:

        ```python
        from prefect import flow
        from prefect_aws import AwsCredentials
        from prefect_aws.s3 import s3_upload


        @flow
        async def example_s3_upload_flow():
            aws_credentials = AwsCredentials(
                aws_access_key_id="acccess_key_id",
                aws_secret_access_key="secret_access_key"
            )
            with open("data.csv", "rb") as file:
                key = await s3_upload(
                    bucket="bucket",
                    key="data.csv",
                    data=file.read(),
                    aws_credentials=aws_credentials,
                )

        example_s3_upload_flow()
        ```
    """
    logger = get_run_logger()

    key = key or str(uuid.uuid4())

    logger.info("Uploading object to bucket %s with key %s", bucket, key)

    s3_client = aws_credentials.get_boto3_session().client(
        "s3", **aws_client_parameters.get_params_override()
    )
    stream = io.BytesIO(data)
    await run_sync_in_worker_thread(
        s3_client.upload_fileobj, stream, Bucket=bucket, Key=key
    )

    return key


def _list_objects_sync(page_iterator: PageIterator):
    """
    Synchronous method to collect S3 objects into a list

    Args:
        page_iterator: AWS Paginator for S3 objects

    Returns:
        List[Dict]: List of object information
    """
    return [content for page in page_iterator for content in page.get("Contents", [])]


@task
async def s3_list_objects(
    bucket: str,
    aws_credentials: AwsCredentials,
    aws_client_parameters: AwsClientParameters = AwsClientParameters(),
    prefix: str = "",
    delimiter: str = "",
    page_size: Optional[int] = None,
    max_items: Optional[int] = None,
    jmespath_query: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Lists details of objects in a given S3 bucket.

    Args:
        bucket: Name of bucket to list items from. Required if a default value was not
            supplied when creating the task.
        aws_credentials: Credentials to use for authentication with AWS.
        aws_client_parameters: Custom parameter for the boto3 client initialization..
        prefix: Used to filter objects with keys starting with the specified prefix.
        delimiter: Character used to group keys of listed objects.
        page_size: Number of objects to return in each request to the AWS API.
        max_items: Maximum number of objects that to be returned by task.
        jmespath_query: Query used to filter objects based on object attributes refer to
            the [boto3 docs](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/paginators.html#filtering-results-with-jmespath)
            for more information on how to construct queries.

    Returns:
        A list of dictionaries containing information about the objects retrieved. Refer
            to the boto3 docs for an example response.

    Example:
        List all objects in a bucket:

        ```python
        from prefect import flow
        from prefect_aws import AwsCredentials
        from prefect_aws.s3 import s3_list_objects


        @flow
        async def example_s3_list_objects_flow():
            aws_credentials = AwsCredentials(
                aws_access_key_id="acccess_key_id",
                aws_secret_access_key="secret_access_key"
            )
            objects = await s3_list_objects(
                bucket="data_bucket",
                aws_credentials=aws_credentials
            )

        example_s3_list_objects_flow()
        ```
    """  # noqa E501
    logger = get_run_logger()
    logger.info("Listing objects in bucket %s with prefix %s", bucket, prefix)

    s3_client = aws_credentials.get_boto3_session().client(
        "s3", **aws_client_parameters.get_params_override()
    )
    paginator = s3_client.get_paginator("list_objects_v2")
    page_iterator = paginator.paginate(
        Bucket=bucket,
        Prefix=prefix,
        Delimiter=delimiter,
        PaginationConfig={"PageSize": page_size, "MaxItems": max_items},
    )
    if jmespath_query:
        page_iterator = page_iterator.search(f"{jmespath_query} | {{Contents: @}}")

    return await run_sync_in_worker_thread(_list_objects_sync, page_iterator)


class S3Bucket(ReadableFileSystem, WritableFileSystem):

    """
    Block used to store data using AWS S3 or S3-compatible object storage like MinIO.

    Args:
        bucket_name: Name of your bucket.
        aws_credentials: A block containing your credentials (choose this
            or minio_credentials).
        minio_credentials: A block containing your credentials (choose this
            or aws_credentials).
        basepath: Used when you don't want to read/write at base level.
        endpoint_url: Used for non-AWS configuration. When unspecified,
            defaults to AWS.

    Example:
        Load stored S3Bucket configuration:
        ```python
        from prefect_aws.s3 import S3Bucket

        s3bucket_block = S3Bucket.load("BLOCK_NAME")
        ```
    """

    # change
    _logo_url = "https://images.ctfassets.net/gm98wzqotmnx/uPezmBzEv4moXKdQJ3YyL/a1f029b423cf67f474d1eee33c1463d7/pngwing.com.png?h=250"  # noqa
    _block_type_name = "S3 Bucket"

    bucket_name: str
    minio_credentials: Optional[MinIOCredentials]
    aws_credentials: Optional[AwsCredentials]
    basepath: Optional[Path]
    endpoint_url: Optional[str]

    @validator("basepath", pre=True)
    def cast_pathlib(cls, value):

        """
        If basepath provided, it means we aren't writing to the root directory
        of the bucket. We need to ensure that it is a valid path. This is called
        when the S3Bucket block is instantiated.
        """

        if isinstance(value, Path):
            return str(value)
        return value

    @root_validator(pre=True)
    def check_credentials(cls, values):

        """
        Ensure exactly 1 of 2 optional credentials fields has been provided by
        user.
        """

        minio_creds_exist = bool(values.get("minio_credentials"))
        aws_creds_exist = bool(values.get("aws_credentials"))

        # if both credentials fields provided
        if minio_creds_exist and aws_creds_exist:
            raise ValueError(
                "S3Bucket accepts a minio_credentials field or an"
                "aws_credentials field but not both."
            )
        # if neither credentials fields provided
        if not minio_creds_exist and not aws_creds_exist:
            raise ValueError(
                "S3Bucket requires either a minio_credentials"
                "field or an aws_credentials field."
            )
        return values

    def _resolve_path(self, path: str) -> Path:

        """
        A helper function used in write_path to join `self.basepath` and `path`.

        Args:

            path: Name of the key, e.g. "file1". Each object in your
                bucket has a unique key (or key name).

        """

        path = path or str(uuid4())

        # If basepath provided, it means we won't write to the root dir of
        # the bucket. So we need to add it on the front of the path.
        path = str(Path(self.basepath) / path) if self.basepath else path

        return path

    def _get_s3_client(self) -> boto3.client:

        """
        Authenticate MinIO credentials or AWS credentials and return an S3 client.
        This is a helper function called by read_path() or write_path().
        """

        if self.minio_credentials:
            s3_client = self.minio_credentials.get_boto3_session().client(
                service_name="s3", endpoint_url=self.endpoint_url
            )

        elif self.aws_credentials:
            s3_client = self.aws_credentials.get_boto3_session().client(
                service_name="s3"
            )

        return s3_client

    @sync_compatible
    async def read_path(self, path: str) -> bytes:

        """
        Read specified path from S3 and return contents. Provide the entire
        path to the key in S3.

        Args:
            path: Entire path to (and including) the key.

        Example:
            Read "subfolder/file1" contents from an S3 bucket named "bucket":
            ```python
            from prefect_aws import AwsCredentials
            from prefect_aws.s3 import S3Bucket

            aws_creds = AwsCredentials(
                aws_access_key_id=AWS_ACCESS_KEY_ID,
                aws_secret_access_key=AWS_SECRET_ACCESS_KEY
            )

            s3_bucket_block = S3Bucket(
                bucket_name="bucket",
                aws_credentials=aws_creds,
                basepath="subfolder"
            )

            key_contents = s3_bucket_block.read_path(path="subfolder/file1")
            ```
        """

        return await run_sync_in_worker_thread(self._read_sync, path)

    def _read_sync(self, key: str) -> bytes:

        """
        Called by read_path(). Creates an S3 client and retrieves the
        contents from  a specified path.
        """

        s3_client = self._get_s3_client()

        with io.BytesIO() as stream:

            s3_client.download_fileobj(Bucket=self.bucket_name, Key=key, Fileobj=stream)
            stream.seek(0)
            output = stream.read()
            return output

    @sync_compatible
    async def write_path(self, path: str, content: bytes) -> str:

        """
        Writes to an S3 bucket.

        Args:

            path: The key name. Each object in your bucket has a unique
                key (or key name).
            content: What you are uploading to S3.

        Example:

            Write data to the path `dogs/small_dogs/havanese` in an S3 Bucket:
            ```python
            from prefect_aws import MinioCredentials
            from prefect_aws.s3 import S3Bucket

            minio_creds = MinIOCredentials(
                minio_root_user = "minioadmin",
                minio_root_password = "minioadmin",
            )

            s3_bucket_block = S3Bucket(
                bucket_name="bucket",
                minio_credentials=minio_creds,
                basepath="dogs/smalldogs",
                endpoint_url="http://localhost:9000",
            )
            s3_havanese_path = s3_bucket_block.write_path(path="havanese", content=data)
            ```
        """

        path = self._resolve_path(path)

        await run_sync_in_worker_thread(self._write_sync, path, content)

        return path

    def _write_sync(self, key: str, data: bytes) -> None:

        """
        Called by write_path(). Creates an S3 client and uploads a file
        object.
        """

        s3_client = self._get_s3_client()

        with io.BytesIO(data) as stream:

            s3_client.upload_fileobj(Fileobj=stream, Bucket=self.bucket_name, Key=key)
