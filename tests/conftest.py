import pytest
from botocore import UNSIGNED
from botocore.client import Config
from prefect.testing.utilities import prefect_test_harness

from prefect_aws import AwsCredentials
from prefect_aws.client_parameters import AwsClientParameters


# added to eliminate warnings
def pytest_configure(config):
    config.addinivalue_line(
        "markers", "is_public: mark test as using public S3 bucket or not"
    )


@pytest.fixture(scope="session", autouse=True)
def prefect_db():
    with prefect_test_harness():
        yield


@pytest.fixture
def aws_credentials():
    return AwsCredentials(
        aws_access_key_id="access_key_id",
        aws_secret_access_key="secret_access_key",
        region_name="us-east-1",
    )


@pytest.fixture
def aws_client_parameters_custom_endpoint():
    return AwsClientParameters(endpoint_url="http://custom.internal.endpoint.org")


@pytest.fixture
def aws_client_parameters_empty():
    return AwsClientParameters()


@pytest.fixture
def aws_client_parameters_public_bucket():
    return AwsClientParameters(config=Config(signature_version=UNSIGNED))
