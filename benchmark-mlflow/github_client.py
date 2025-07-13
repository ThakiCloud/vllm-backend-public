import base64
import requests
import yaml
import logging
from typing import Dict, Optional

from models import GitHubConfig, GitHubFileUpdate
from config import ARGO_FILE_PATH

logger = logging.getLogger(__name__)

class GitHubClient:
    """GitHub API 클라이언트"""
    
    def __init__(self, config: GitHubConfig):
        """
        Args:
            config: GitHub 설정 정보
        """
        self.config = config
        self.base_url = "https://api.github.com"
        self.headers = {
            'Authorization': f'token {config.token}',
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'MLflow-GitHub-Integration/1.0'
        }
    
    def get_file_content(self, file_path: str, branch: str = "main") -> Optional[Dict]:
        """
        GitHub에서 파일 내용 가져오기
        
        Args:
            file_path: 파일 경로
            branch: 브랜치명
            
        Returns:
            파일 정보 딕셔너리 또는 None
        """
        try:
            url = f"{self.base_url}/repos/{self.config.repo_owner}/{self.config.repo_name}/contents/{file_path}"
            params = {'ref': branch}
            
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            
            logger.debug(f"파일 내용 가져오기 성공: {file_path}")
            return response.json()
            
        except requests.exceptions.RequestException as e:
            logger.error(f"파일 내용 가져오기 실패: {file_path} - {e}")
            return None
    
    def update_file(self, file_update: GitHubFileUpdate) -> Optional[Dict]:
        """
        GitHub에서 파일 업데이트
        
        Args:
            file_update: 파일 업데이트 정보
            
        Returns:
            업데이트 결과 딕셔너리 또는 None
        """
        try:
            url = f"{self.base_url}/repos/{self.config.repo_owner}/{self.config.repo_name}/contents/{file_update.file_path}"
            
            # 콘텐츠를 base64로 인코딩
            content_encoded = base64.b64encode(file_update.content.encode('utf-8')).decode('utf-8')
            
            data = {
                'message': file_update.commit_message,
                'content': content_encoded,
                'branch': file_update.branch
            }
            
            if file_update.sha:
                data['sha'] = file_update.sha
            
            response = requests.put(url, headers=self.headers, json=data)
            response.raise_for_status()
            
            logger.info(f"파일 업데이트 성공: {file_update.file_path}")
            return response.json()
            
        except requests.exceptions.RequestException as e:
            logger.error(f"파일 업데이트 실패: {file_update.file_path} - {e}")
            return None
    
    def update_yaml_models(self, run_id: str, model_name: str, version: str, experiment_id: str = "1", model_id: str = None) -> bool:
        """
        model_name.yaml 파일의 global 섹션(experimentId, runid, timestamp) 업데이트
        
        Args:
            run_id: MLflow 실행 ID
            model_name: 모델 이름
            version: 모델 버전
            experiment_id: MLflow 실험 ID
            
        Returns:
            업데이트 성공 여부
        """
        try:
            from datetime import datetime
            
            # model_name을 파일명으로 사용
            yaml_file_path = f"{model_name}.yaml"
            
            # 기존 파일 내용 가져오기 (없으면 새로 생성)
            file_info = self.get_file_content(yaml_file_path)
            file_sha = None
            
            if file_info:
                # 파일이 존재하는 경우 - global 섹션만 업데이트
                content = base64.b64decode(file_info['content']).decode('utf-8')
                yaml_data = yaml.safe_load(content) or {}
                file_sha = file_info['sha']
                
                # global 섹션 업데이트
                if 'global' not in yaml_data:
                    yaml_data['global'] = {}
                    
                yaml_data['global']['experimentId'] = experiment_id
                yaml_data['global']['runid'] = run_id
                yaml_data['global']['modelid'] = model_id
                yaml_data['global']['timestamp'] = datetime.now().strftime("%Y%m%d-%H%M%S")
                yaml_data['global']['modelName'] = model_name
                yaml_data['global']['modelVersion'] = version
                
            else:
                # 파일이 없는 경우 - 전체 템플릿으로 새로 생성
                yaml_data = self._get_yaml_template(run_id, experiment_id, model_name, version, model_id)
            
            # YAML 다시 직렬화
            updated_content = yaml.dump(yaml_data, default_flow_style=False, allow_unicode=True, sort_keys=False)
            
            # 커밋 메시지 생성
            commit_message = f"Update {model_name} - version: {version}, runid: {run_id}"
            
            # 파일 업데이트
            file_update = GitHubFileUpdate(
                file_path=yaml_file_path,
                content=updated_content,
                commit_message=commit_message,
                sha=file_sha
            )
            
            result = self.update_file(file_update)
            
            if result:
                logger.info(f"GitHub 레포의 {model_name}.yaml 업데이트 완료: experimentId={experiment_id}, runid={run_id}, version={version}")
                return True
            else:
                return False
                
        except Exception as e:
            logger.error(f"YAML 파일 업데이트 중 오류 발생: {e}")
            return False

    def add_model_to_argo_application(self, model_name: str) -> bool:
        """
        argo-application.yaml 파일의 valueFiles 섹션에 새로운 모델 파일 추가
        
        Args:
            model_name: 모델 이름
            
        Returns:
            업데이트 성공 여부
        """
        try:
            argo_file_path = ARGO_FILE_PATH
            yaml_file_name = f"{model_name}.yaml"
            
            # 기존 파일 내용 가져오기
            file_info = self.get_file_content(argo_file_path)
            
            if not file_info:
                logger.error(f"argo-application.yaml 파일을 찾을 수 없습니다.")
                return False
            
            # 파일 내용 디코딩
            content = base64.b64decode(file_info['content']).decode('utf-8')
            yaml_data = yaml.safe_load(content)
            
            # valueFiles 섹션 확인 및 업데이트
            if 'spec' not in yaml_data:
                yaml_data['spec'] = {}
            if 'source' not in yaml_data['spec']:
                yaml_data['spec']['source'] = {}
            if 'helm' not in yaml_data['spec']['source']:
                yaml_data['spec']['source']['helm'] = {}
            if 'valueFiles' not in yaml_data['spec']['source']['helm']:
                yaml_data['spec']['source']['helm']['valueFiles'] = []
            
            # 이미 존재하는지 확인
            if yaml_file_name not in yaml_data['spec']['source']['helm']['valueFiles']:
                yaml_data['spec']['source']['helm']['valueFiles'].append(yaml_file_name)
                logger.info(f"argo-application.yaml에 {yaml_file_name} 추가")
                
                # YAML 다시 직렬화
                updated_content = yaml.dump(yaml_data, default_flow_style=False, allow_unicode=True, sort_keys=False)
                
                # 커밋 메시지 생성
                commit_message = f"Add {yaml_file_name} to argo-application valueFiles"
                
                # 파일 업데이트
                file_update = GitHubFileUpdate(
                    file_path=argo_file_path,
                    content=updated_content,
                    commit_message=commit_message,
                    sha=file_info['sha']
                )
                
                result = self.update_file(file_update)
                
                if result:
                    logger.info(f"argo-application.yaml 업데이트 완료: {yaml_file_name} 추가")
                    return True
                else:
                    return False
            else:
                logger.info(f"{yaml_file_name}이 이미 argo-application.yaml에 존재합니다.")
                return True
                
        except Exception as e:
            logger.error(f"argo-application.yaml 업데이트 중 오류 발생: {e}")
            return False
    
    def _get_yaml_template(self, run_id: str, experiment_id: str = "1", model_name: str = "Qwen/Qwen3-0.6B", version: str = "1", model_id: str = None) -> Dict:
        """
        새로운 YAML 파일을 위한 템플릿 생성
        
        Args:
            run_id: MLflow 실행 ID
            experiment_id: MLflow 실험 ID
            model_name: 모델 이름
            version: 모델 버전
            
        Returns:
            YAML 템플릿 딕셔너리
        """
        from datetime import datetime
        model_name = model_name.replace(".", "-").replace("_", "-")
        lower_model_name = model_name.lower()
        return {
            'global': {
                'experimentId': experiment_id,
                'runid': run_id,
                'modelid': model_id,
                'timestamp': datetime.now().strftime("%Y%m%d-%H%M%S"),
                'modelName': model_name,
                'modelVersion': version
            },
            'vllm': {
                'vllm': {
                    'model': f"/data/local_models/{model_name}",
                    'maxModelLen': 4096,
                    'gpuMemoryUtilization': 0.9,
                    'trust_remote_code': True
                },
                'nodeSelector': {
                    'nvidia.com/mig-4g.47gb.product': "NVIDIA-H100-NVL-MIG-4g.47gb"
                },
                'affinity': {
                    'nodeAffinity': {
                        'required': {
                            'nodeSelectorTerm': {
                                'matchExpressions': [
                                    {
                                        'key': 'nvidia.com/mig-4g.47gb.product',
                                        'operator': 'In',
                                        'values': ["NVIDIA-H100-NVL-MIG-4g.47gb"]
                                    }
                                ]
                            }
                        }
                    }
                },
                'fullnameOverride': f"vllm-{lower_model_name}",
                'initContainers': {
                    'enabled': True
                },
                'replicaCount': 1,
                'autoscaling': {
                    'enabled': False
                },
                'resources': {
                    'limits': {
                        'memory': "8Gi",
                        'cpu': "4"
                    },
                    'requests': {
                        'memory': "4Gi",
                        'cpu': "2"
                    }
                },
                'serviceAccount': {
                    'create': True,
                    'annotations': {},
                    'name': f"vllm-{lower_model_name}-sa"
                },
                'env': [
                    {'name': 'CUDA_VISIBLE_DEVICES', 'value': "0"},
                    {'name': 'TORCH_COMPILE_DISABLE', 'value': "1"},
                    {'name': 'TORCHINDUCTOR_CACHE_DIR', 'value': "/tmp/torch_cache"},
                    {'name': 'USER', 'value': "vllm"},
                    {'name': 'VLLM_PORT', 'value': "8000"}
                ],
                'persistence': {
                    'enabled': True,
                    'size': '200Gi',
                    'storageClass': "nfs-mig",
                    'mountPath': '/data'
                },
                'hfToken': {
                    'enabled': True
                },
                'ingress': {
                    'enabled': False
                },
                'monitoring': {
                    'enabled': True,
                    'dcgmExporter': {
                        'enabled': True
                    }
                },
                'hpa': {
                    'enabled': False,
                    'minReplicas': 1,
                    'maxReplicas': 1
                },
                'rollouts': {
                    'enabled': True,
                    'strategy': "canary",
                    'canary': {
                        'steps': [
                            {'setWeight': 10},
                            {'pause': {'duration': '1m'}},
                            {'setWeight': 20},
                            {'pause': {'duration': '1m'}}
                        ],
                        'maxUnavailable': 0,
                        'maxSurge': "25%"
                    }
                }
            }
        }
    
    def test_connection(self) -> bool:
        """
        GitHub API 연결 테스트
        
        Returns:
            연결 성공 여부
        """
        try:
            url = f"{self.base_url}/repos/{self.config.repo_owner}/{self.config.repo_name}"
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            
            logger.info(f"GitHub 연결 테스트 성공: {self.config.repo_owner}/{self.config.repo_name}")
            return True
            
        except requests.exceptions.RequestException as e:
            logger.error(f"GitHub 연결 테스트 실패: {e}")
            return False
    
    def get_repository_info(self) -> Optional[Dict]:
        """
        저장소 정보 가져오기
        
        Returns:
            저장소 정보 딕셔너리 또는 None
        """
        try:
            url = f"{self.base_url}/repos/{self.config.repo_owner}/{self.config.repo_name}"
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            
            return response.json()
            
        except requests.exceptions.RequestException as e:
            logger.error(f"저장소 정보 가져오기 실패: {e}")
            return None 