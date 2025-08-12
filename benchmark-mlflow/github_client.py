import base64
import requests
import yaml
import logging
from typing import Dict, Optional

from models import GitHubConfig, GitHubFileUpdate
from config import (ARGO_FILE_PATH, YAML_TEMPLATE_PATH, TEMPLATE_REPO_OWNER, TEMPLATE_REPO_NAME, 
                   ARGO_REPO_OWNER, ARGO_REPO_NAME, ARGOCD_PROJECT_NAME, ARGOCD_REPO_URL, ARGOCD_NAMESPACE,
                   ARGO_PROJECT_TEMPLATE_PATH, ARGO_APPLICATION_PATH, ARGO_PROJECT_PATH, YAML_MODEL_FILE_PATH, 
                   BENCHMARK_EVAL_URL, get_yaml_model_file_path, get_yaml_template_path)
from vllm_processor import VLLMProcessor
from tensorrt_llm_processor import TensorRTLLMProcessor

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
            'Authorization': f'Bearer {config.token}',
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'MLflow-GitHub-Integration/1.0'
        }
        
        # Initialize processors
        self.processors = {
            'vllm': VLLMProcessor(BENCHMARK_EVAL_URL),
            'tensorrt-llm': TensorRTLLMProcessor(BENCHMARK_EVAL_URL)
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
            logger.debug(f"파일 내용 가져오기 실패: {file_path} - {e}")
            return None
    
    def get_template_file_content(self, file_path: str, branch: str = "main") -> Optional[Dict]:
        """
        템플릿 레포에서 파일 내용 가져오기
        
        Args:
            file_path: 파일 경로
            branch: 브랜치명
            
        Returns:
            파일 정보 딕셔너리 또는 None
        """
        try:
            url = f"{self.base_url}/repos/{TEMPLATE_REPO_OWNER}/{TEMPLATE_REPO_NAME}/contents/{file_path}"
            params = {'ref': branch}
            
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            
            logger.debug(f"템플릿 파일 내용 가져오기 성공: {file_path} from {TEMPLATE_REPO_OWNER}/{TEMPLATE_REPO_NAME}")
            return response.json()
            
        except requests.exceptions.RequestException as e:
            logger.error(f"템플릿 파일 내용 가져오기 실패: {file_path} from {TEMPLATE_REPO_OWNER}/{TEMPLATE_REPO_NAME} - {e}")
            return None
    
    def get_argo_file_content(self, file_path: str, branch: str = "main") -> Optional[Dict]:
        """
        Argo 레포에서 파일 내용 가져오기
        
        Args:
            file_path: 파일 경로
            branch: 브랜치명
            
        Returns:
            파일 정보 딕셔너리 또는 None
        """
        try:
            url = f"{self.base_url}/repos/{ARGO_REPO_OWNER}/{ARGO_REPO_NAME}/contents/{file_path}"
            params = {'ref': branch}
            
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            
            logger.debug(f"Argo 파일 내용 가져오기 성공: {file_path} from {ARGO_REPO_OWNER}/{ARGO_REPO_NAME}")
            return response.json()
            
        except requests.exceptions.RequestException as e:
            logger.debug(f"Argo 파일 내용 가져오기 실패: {file_path} from {ARGO_REPO_OWNER}/{ARGO_REPO_NAME} - {e}")
            return None
    
    def update_argo_file(self, file_update: GitHubFileUpdate) -> Optional[Dict]:
        """
        Argo 레포에서 파일 업데이트
        
        Args:
            file_update: 파일 업데이트 정보
            
        Returns:
            업데이트 결과 딕셔너리 또는 None
        """
        try:
            url = f"{self.base_url}/repos/{ARGO_REPO_OWNER}/{ARGO_REPO_NAME}/contents/{file_update.file_path}"
            
            # 콘텐츠를 base64로 인코딩
            content_encoded = base64.b64encode(file_update.content.encode('utf-8')).decode('utf-8')
            
            data = {
                'message': file_update.commit_message,
                'content': content_encoded,
                'branch': file_update.branch
            }
            
            response = requests.put(url, headers=self.headers, json=data)
            response.raise_for_status()
            
            logger.debug(f"Argo 파일 업데이트 성공: {file_update.file_path} to {ARGO_REPO_OWNER}/{ARGO_REPO_NAME}")
            return response.json()
            
        except requests.exceptions.RequestException as e:
            logger.debug(f"Argo 파일 업데이트 실패: {file_update.file_path} to {ARGO_REPO_OWNER}/{ARGO_REPO_NAME} - {e}")
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
            
            response = requests.put(url, headers=self.headers, json=data)
            response.raise_for_status()
            
            logger.debug(f"파일 업데이트 성공: {file_update.file_path}")
            return response.json()
            
        except requests.exceptions.RequestException as e:
            logger.debug(f"파일 업데이트 실패: {file_update.file_path} - {e}")
            return None
    
    def update_yaml_models(self, engine_type: str, run_id: str, model_name: str, version: str, experiment_id: str = "1", model_id: str = None, existing_file: Optional[Dict] = None) -> bool:
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
            
            success_count = 0
            
            engine_yaml_path = get_yaml_model_file_path(engine_type)
            if engine_yaml_path:
                yaml_file_path = f"{engine_yaml_path}/{model_name}.yaml"
            else:
                yaml_file_path = f"{model_name}.yaml"
            
            # 각 엔진별 템플릿 처리
            yaml_data = self._get_yaml_template_for_engine(run_id, experiment_id, model_name, version, model_id, engine_type)
            if not yaml_data:
                logger.error(f"템플릿을 가져올 수 없어 {engine_type}/{model_name}.yaml 파일을 생성할 수 없습니다.")
                return False
            
            # YAML 직렬화 및 파일 업데이트
            updated_content = yaml.dump(yaml_data, default_flow_style=False, allow_unicode=True, sort_keys=False)
            commit_message = f"Update {model_name} ({engine_type}) - version: {version}, runid: {run_id}"
            
            file_update = GitHubFileUpdate(
                file_path=yaml_file_path,
                content=updated_content,
                commit_message=commit_message
            )
            
            result = self.update_file(file_update)
            if result:
                logger.info(f"GitHub 레포의 {engine_type}/{model_name}.yaml 업데이트 완료")
                success_count += 1
            
            return success_count == 1
                
        except Exception as e:
            logger.error(f"YAML 파일 업데이트 중 오류 발생: {e}")
            return False

    def add_model_to_argo_application(self, engine_type: str, model_name: str, project_name: str = None, repo_url: str = None, namespace: str = None) -> bool:
        """
        ArgoCD Application 템플릿을 사용해서 새로운 모델용 Application 생성
        
        Args:
            model_name: 모델 이름
            project_name: ArgoCD 프로젝트 이름
            repo_url: Git 레포 URL
            namespace: Kubernetes 네임스페이스
            
        Returns:
            생성 성공 여부
        """
        try:
            # 기본값 설정
            if project_name is None:
                project_name = ARGOCD_PROJECT_NAME
            if repo_url is None:
                repo_url = ARGOCD_REPO_URL
            if namespace is None:
                namespace = ARGOCD_NAMESPACE
            
            success_count = 0
            
            if engine_type in self.processors:
                success = self._create_single_argo_application(model_name, engine_type, project_name, repo_url, namespace)
                if success:
                    success_count += 1
            else:
                logger.error(f"지원하지 않는 inference engine type: {engine_type}")
            
            return success_count == 1
                    
        except Exception as e:
            logger.error(f"ArgoCD Application 추가 중 오류 발생: {e}")
            return False

    def _create_single_argo_application(self, model_name: str, engine_type: str, project_name: str, repo_url: str, namespace: str) -> bool:
        """
        단일 엔진 타입에 대한 ArgoCD Application 생성
        
        Args:
            model_name: 모델 이름
            engine_type: 엔진 타입
            project_name: ArgoCD 프로젝트 이름
            repo_url: Git 레포 URL
            namespace: Kubernetes 네임스페이스
            
        Returns:
            생성 성공 여부
        """
        try:
            processor = self.processors[engine_type]
            application_name = processor.get_application_name(model_name)
            
            if ARGO_APPLICATION_PATH:
                application_file_path = f"{ARGO_APPLICATION_PATH}/{application_name}.yaml"
            else:
                application_file_path = f"{application_name}.yaml"
            value_file = f"{model_name}"
            
            # ArgoCD Application 템플릿에서 가져오기
            template_info = self.get_argo_file_content(ARGO_FILE_PATH)
            
            if not template_info:
                logger.error(f"Argo 레포에서 ArgoCD Application 템플릿을 찾을 수 없습니다: {ARGO_FILE_PATH}")
                return False
            
            # 템플릿 내용 디코딩
            template_content = base64.b64decode(template_info['content']).decode('utf-8')
            
            # 템플릿 placeholder 채우기
            application_content = template_content.format(
                path=engine_type,
                application_name=application_name,
                project_name=project_name,
                repo_url=repo_url,
                value_file=value_file,
                namespace=namespace
            )
            
            # 기존 파일이 있는지 확인
            existing_file_info = self.get_argo_file_content(application_file_path)
            
            if existing_file_info:
                # 기존 내용과 비교
                existing_content = base64.b64decode(existing_file_info['content']).decode('utf-8')
                if existing_content.strip() == application_content.strip():
                    logger.debug(f"ArgoCD Application이 이미 동일한 내용으로 존재합니다: {application_file_path}")
                    return True
            
            # 커밋 메시지 생성
            action = "Update" if existing_file_info else "Create"
            commit_message = f"{action} ArgoCD Application for {model_name}"
            
            # 파일 업데이트/생성
            file_update = GitHubFileUpdate(
                file_path=application_file_path,
                content=application_content,
                commit_message=commit_message
            )
            
            result = self.update_argo_file(file_update)
            
            if result:
                return True
            else:
                return False
                
        except Exception as e:
            return False
    
    def create_argo_project(self, project_name: str = None, repo_url: str = None, namespace: str = None) -> bool:
        """
        ArgoCD AppProject 템플릿을 사용해서 새로운 프로젝트 생성
        
        Args:
            project_name: ArgoCD 프로젝트 이름
            repo_url: Git 레포 URL
            namespace: Kubernetes 네임스페이스
            
        Returns:
            생성 성공 여부
        """
        try:
            # 기본값 설정
            if project_name is None:
                project_name = ARGOCD_PROJECT_NAME
            if repo_url is None:
                repo_url = ARGOCD_REPO_URL
            if namespace is None:
                namespace = ARGOCD_NAMESPACE
            
            # Project 파일명 생성
            if ARGO_PROJECT_PATH:
                project_file_path = f"{ARGO_PROJECT_PATH}/{project_name}.yaml"
            else:
                project_file_path = f"{project_name}.yaml"
            
            # ArgoCD AppProject 템플릿에서 가져오기
            template_info = self.get_argo_file_content(ARGO_PROJECT_TEMPLATE_PATH)
            
            if not template_info:
                logger.error(f"Argo 레포에서 ArgoCD AppProject 템플릿을 찾을 수 없습니다: {ARGO_PROJECT_TEMPLATE_PATH}")
                return False
            
            # 템플릿 내용 디코딩
            template_content = base64.b64decode(template_info['content']).decode('utf-8')
            
            # 템플릿 placeholder 채우기
            project_content = template_content.format(
                project_name=project_name,
                repo_url=repo_url,
                namespace=namespace
            )
            
            # 기존 파일이 있는지 확인
            existing_file_info = self.get_argo_file_content(project_file_path)
            
            if existing_file_info:
                # 기존 내용과 비교
                existing_content = base64.b64decode(existing_file_info['content']).decode('utf-8')
                if existing_content.strip() == project_content.strip():
                    logger.debug(f"ArgoCD AppProject가 이미 동일한 내용으로 존재합니다: {project_file_path}")
                    return True
            
            # 커밋 메시지 생성
            action = "Update" if existing_file_info else "Create"
            commit_message = f"{action} ArgoCD AppProject: {project_name}"
            
            # 파일 업데이트/생성
            file_update = GitHubFileUpdate(
                file_path=project_file_path,
                content=project_content,
                commit_message=commit_message
            )
            
            result = self.update_argo_file(file_update)
            
            if result:
                return True
            else:
                return False
                
        except Exception as e:
            return False
    
    def _get_yaml_template_for_engine(self, run_id: str, experiment_id: str = "1", model_name: str = "Qwen/Qwen3-0.6B", version: str = "1", model_id: str = None, engine_type: str = None) -> Dict:
        """
        특정 엔진 타입에 대한 YAML 템플릿 생성
        
        Args:
            run_id: MLflow 실행 ID
            experiment_id: MLflow 실험 ID
            model_name: 모델 이름
            version: 모델 버전
            model_id: 모델 ID
            engine_type: 특정 엔진 타입 (vllm, tensorrt-llm)
            
        Returns:
            YAML 템플릿 딕셔너리
        """
        try:
            if not engine_type or engine_type not in self.processors:
                logger.error(f"지원하지 않는 엔진 타입: {engine_type}")
                return None
            
            # 각 엔진별 템플릿 경로 생성
            template_path = get_yaml_template_path(engine_type)
            
            # 템플릿 파일 가져오기
            template_file_info = self.get_template_file_content(template_path)
            
            if not template_file_info:
                logger.error(f"템플릿 파일을 찾을 수 없습니다: {template_path}")
                return None
            
            # 템플릿 파일 내용 파싱
            content = base64.b64decode(template_file_info['content']).decode('utf-8')
            yaml_data = yaml.safe_load(content) or {}
            logger.debug(f"템플릿 레포에서 {engine_type} 템플릿 파일 로드 완료: {template_path}")
            
            # 프로세서를 사용하여 YAML 처리
            processor = self.processors[engine_type]
            yaml_data = processor.process_yaml_data(yaml_data, model_name, run_id, experiment_id, model_id, version)
            logger.debug(f"프로세서를 사용하여 YAML 처리 완료: {engine_type}")
            
            return yaml_data
            
        except Exception as e:
            logger.error(f"엔진별 템플릿 로드 중 오류 발생: {e}")
            return None

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