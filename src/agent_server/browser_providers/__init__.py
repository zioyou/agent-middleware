import os
from .docker_provider import DockerProvider
from .k8s_provider import KubernetesProvider

def get_provider():
    provider_type = os.getenv("BROWSER_MANAGER_RUNTIME", "docker").lower()
    if provider_type == "kubernetes" or provider_type == "k8s":
        return KubernetesProvider()
    return DockerProvider()
