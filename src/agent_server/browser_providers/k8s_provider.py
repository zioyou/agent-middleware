import os
import asyncio
from .base import BrowserProviderBase
from kubernetes import client, config
from kubernetes.client.rest import ApiException

BROWSER_IMAGE = os.getenv("BROWSER_IMAGE", "agent-browser:latest")
K8S_NAMESPACE = os.getenv("K8S_NAMESPACE", "agent-system")

class KubernetesProvider(BrowserProviderBase):
    def __init__(self):
        try:
            config.load_incluster_config()
        except config.config_exception.ConfigException:
            try:
                config.load_kube_config()
            except Exception as e:
                print(f"[KubernetesProvider] Cannot load kube config: {e}")
                
        self.core_v1 = client.CoreV1Api()
        self.custom_api = client.CustomObjectsApi()
        
    async def _k8s(self, fn):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, fn)

    async def create_session(self, safe_id: str, thread_id: str) -> None:
        pod_name = f"agent-browser-{safe_id}"
        
        await self.remove_session(safe_id)
        
        env_vars = [
            client.V1EnvVar(name="OPENAI_API_KEY", value=os.getenv("OPENAI_API_KEY", "")),
            client.V1EnvVar(name="GOOGLE_API_KEY", value=os.getenv("GOOGLE_API_KEY", "")),
            client.V1EnvVar(name="LLM_PROVIDER", value=os.getenv("LLM_PROVIDER", "google")),
            client.V1EnvVar(name="VISION_MODEL", value=os.getenv("VISION_MODEL", "gemini-2.0-flash")),
        ]

        pod = client.V1Pod(
            api_version="v1",
            kind="Pod",
            metadata=client.V1ObjectMeta(
                name=pod_name,
                labels={"app": "agent-browser", "session": safe_id}
            ),
            spec=client.V1PodSpec(
                containers=[
                    client.V1Container(
                        name="browser",
                        image=BROWSER_IMAGE,
                        image_pull_policy="Always",
                        env=env_vars,
                        volume_mounts=[
                            client.V1VolumeMount(name="dshm", mount_path="/dev/shm")
                        ],
                        ports=[
                            client.V1ContainerPort(container_port=6080),
                            client.V1ContainerPort(container_port=8010)
                        ]
                    )
                ],
                volumes=[
                    client.V1Volume(
                        name="dshm",
                        empty_dir=client.V1EmptyDirVolumeSource(medium="Memory", size_limit="2Gi")
                    )
                ]
            )
        )
        
        service = client.V1Service(
            api_version="v1",
            kind="Service",
            metadata=client.V1ObjectMeta(
                name=pod_name,
                labels={"app": "agent-browser", "session": safe_id}
            ),
            spec=client.V1ServiceSpec(
                selector={"app": "agent-browser", "session": safe_id},
                ports=[
                    client.V1ServicePort(name="vnc", port=6080, target_port=6080),
                    client.V1ServicePort(name="api", port=8010, target_port=8010)
                ]
            )
        )
        
        ingress_route = {
            "apiVersion": "traefik.containo.us/v1alpha1",
            "kind": "IngressRoute",
            "metadata": {
                "name": pod_name,
                "namespace": K8S_NAMESPACE
            },
            "spec": {
                "entryPoints": ["web"],
                "routes": [{
                    "match": f"Host(`session-{safe_id}.localhost`)",
                    "kind": "Rule",
                    "services": [{
                        "name": pod_name,
                        "port": 6080
                    }]
                }]
            }
        }

        try:
            await self._k8s(lambda: self.core_v1.create_namespaced_pod(namespace=K8S_NAMESPACE, body=pod))
            await self._k8s(lambda: self.core_v1.create_namespaced_service(namespace=K8S_NAMESPACE, body=service))
            await self._k8s(lambda: self.custom_api.create_namespaced_custom_object(
                group="traefik.containo.us",
                version="v1alpha1",
                namespace=K8S_NAMESPACE,
                plural="ingressroutes",
                body=ingress_route,
            ))
        except ApiException as e:
            print(f"[KubernetesProvider] Create failed: {e}")

    async def is_running(self, safe_id: str) -> bool:
        pod_name = f"agent-browser-{safe_id}"
        try:
            pod = await self._k8s(lambda: self.core_v1.read_namespaced_pod(name=pod_name, namespace=K8S_NAMESPACE))
            return pod.status.phase == "Running"
        except ApiException:
            return False

    async def remove_session(self, safe_id: str) -> None:
        pod_name = f"agent-browser-{safe_id}"
        try:
            await self._k8s(lambda: self.core_v1.delete_namespaced_pod(name=pod_name, namespace=K8S_NAMESPACE))
        except ApiException:
            pass
            
        try:
            await self._k8s(lambda: self.core_v1.delete_namespaced_service(name=pod_name, namespace=K8S_NAMESPACE))
        except ApiException:
            pass

        try:
            await self._k8s(lambda: self.custom_api.delete_namespaced_custom_object(
                group="traefik.containo.us",
                version="v1alpha1",
                namespace=K8S_NAMESPACE,
                plural="ingressroutes",
                name=pod_name,
            ))
        except ApiException:
            pass

    async def cleanup_orphans(self) -> None:
        try:
            pods = await self._k8s(lambda: self.core_v1.list_namespaced_pod(namespace=K8S_NAMESPACE, label_selector="app=agent-browser"))
            for pod in pods.items:
                safe_id = pod.metadata.labels.get("session")
                if safe_id:
                    await self.remove_session(safe_id)
                    print(f"[KubernetesProvider] 🧹 고아 정리: {pod.metadata.name}")
        except Exception as e:
            print(f"[KubernetesProvider] 시작 시 정리 실패: {e}")
