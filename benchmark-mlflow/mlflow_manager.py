import os
import time
import logging
import requests
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from mlflow.tracking import MlflowClient
import base64
import yaml
try:
    from mlflow.entities import ModelVersion, RegisteredModel
except ImportError:
    # MLflow 버전 호환성을 위한 fallback
    try:
        from mlflow.store.entities import ModelVersion, RegisteredModel
    except ImportError:
        ModelVersion = None
        RegisteredModel = None

from models import ModelEvent, PollingResult, GitHubConfig
from github_client import GitHubClient
from config import (BENCHMARK_EVAL_URL, ARGO_AUTO_DEPLOY, ARGOCD_PROJECT_NAME,
                    get_engines_to_process, get_yaml_model_file_path, ENGINE_NAMESPACE, ENGINE_PORT, EVALUATION_ENABLED)

logger = logging.getLogger(__name__)

class MLflowManager:
    """MLflow 폴링 및 관리 클래스"""
    
    def __init__(
        self,
        mlflow_tracking_uri: str,
        polling_interval: int = 60,
        github_config: Optional[GitHubConfig] = None
    ):
        """
        Args:
            mlflow_tracking_uri: MLflow 추적 서버 URI
            polling_interval: 폴링 간격(초)
            github_config: GitHub 설정 정보
        """
        self.mlflow_client = MlflowClient(tracking_uri=mlflow_tracking_uri)
        self.polling_interval = polling_interval
        self.github_config = github_config
        
        # GitHub 클라이언트 초기화
        self.github_client = None
        if github_config:
            self.github_client = GitHubClient(github_config)
        
        # 폴링 제어용
        self._stop_event = threading.Event()
        self._polling_thread: Optional[threading.Thread] = None
    

    
    def _get_latest_model_versions(self) -> List[ModelVersion]:
        """각 모델의 가장 최신 버전만 조회 (GitHub과 비교하여 새로운 것만)"""
        new_versions = []
        existing_files = []
        engine_matches = []
        try:
            registered_models = self.mlflow_client.search_registered_models()
            
            for model in registered_models:
                try:
                    # 모델의 모든 버전 조회
                    versions = self.mlflow_client.search_model_versions(
                        f"name='{model.name}'"
                    )
                    
                    if versions:
                        # 생성 시간 기준으로 정렬하여 가장 최신 버전 선택
                        latest_version = max(versions, key=lambda v: v.creation_timestamp)
                        
                        # GitHub의 기존 파일 검색 (엔진 목록 기반)
                        
                        if self.github_client:
                            # 처리할 엔진 목록 가져오기
                            engines_to_check = get_engines_to_process()
                            
                            for engine_type in engines_to_check:
                                existing_file = None
                                
                                engine_yaml_path = get_yaml_model_file_path(engine_type)
                                
                                if engine_yaml_path:
                                    yaml_file_path = f"{engine_yaml_path}/{model.name}.yaml"
                                else:
                                    yaml_file_path = f"{model.name}.yaml"
                                
                                # 파일 존재 여부 확인
                                engine_file = self.github_client.get_file_content(yaml_file_path)
                                if engine_file:
                                    logger.debug(f"기존 파일 발견: {yaml_file_path}")
                                    existing_file = engine_file 

                                engine_matches.append(engine_type)
                                existing_files.append(existing_file)
                                new_versions.append(latest_version)

                        logger.info(f"최신 모델 버전: {model.name}:{latest_version.version} (run_id: {latest_version.run_id})")
                            
                except Exception as e:
                    logger.warning(f"모델 {model.name}의 버전 조회 실패: {e}")
                    
        except Exception as e:
            logger.error(f"모델 버전 조회 실패: {e}")

        return new_versions, existing_files, engine_matches
    
    def _get_experiment_id_from_run(self, run_id: str) -> str:
        """run_id에서 experiment_id 조회"""
        try:
            run = self.mlflow_client.get_run(run_id)
            return run.info.experiment_id
        except Exception as e:
            logger.warning(f"run_id {run_id}에서 experiment_id 조회 실패: {e}")
            return "1"  # 기본값 반환
    
    def _extract_model_id_from_source(self, source: str) -> str:
        """source에서 model_id 추출"""
        try:
            # source 형식: models:/m-317700115fe54867bd4ce8caaaa77038
            if source and source.startswith('models:/'):
                return source.replace('models:/', '')
            return source
        except Exception as e:
            logger.warning(f"source에서 model_id 추출 실패: {e}")
            return source
    
    def _check_new_models(self) -> List[ModelEvent]:
        """새로운 모델 등록 확인 (GitHub 기반 - 단순화)"""
        # GitHub 기반 상태 관리에서는 모든 중복 체크가 _check_new_versions()에서 이루어지므로
        # 새로운 모델 등록 확인은 단순화함
        events = []
        
        try:
            # 최근 등록된 모델들만 간단히 로그로 출력
            current_models = self.mlflow_client.search_registered_models()
            logger.debug(f"현재 MLflow에 등록된 모델 수: {len(current_models)}")
            
        except Exception as e:
            logger.error(f"MLflow 모델 조회 실패: {e}")
        
        return events
    
    def _check_new_versions(self) -> List[ModelEvent]:
        """새로운 모델 버전 확인"""
        events = []
        
        try:
            # 각 모델의 최신 버전들 확인
            latest_versions, existing_files, engine_matches = self._get_latest_model_versions()
            
            for version, existing_file, engine_match in zip(latest_versions, existing_files, engine_matches):
                if not version.run_id:
                    continue
                
                if existing_file:
                    content = base64.b64decode(existing_file['content']).decode('utf-8')
                    yaml_data = yaml.safe_load(content) or {}
                    
                    if 'global' in yaml_data:
                        existing_model_id = yaml_data['global'].get('modelid', '')
                    
                        # modelid가 같으면 스킵
                        current_model_id = self._extract_model_id_from_source(version.source)
                        if existing_model_id == current_model_id:
                            logger.debug(f"모델 {version.name}의 modelid가 GitHub과 동일하므로 스킵: {current_model_id}")
                            continue
                        
                
                is_new = existing_file is None
                event_type = "model_version_created" if is_new else "model_version_updated"
                
                event = ModelEvent(
                    event_type=event_type,
                    model_name=version.name,
                    version=version.version,
                    run_id=version.run_id,
                    status=version.current_stage,
                    user_id=version.user_id,
                    creation_time=version.creation_timestamp,
                    source=version.source,
                    description=version.description,
                    timestamp=time.time()
                )
                events.append(event)
                
                if is_new:
                    logger.debug(f"새로운 모델 감지: {version.name}:{version.version} (run_id: {version.run_id})")
                else:
                    logger.debug(f"모델 업데이트 감지: {version.name}:{version.version} (run_id: {version.run_id})")
                
                # GitHub 레포 업데이트 (existing_file 정보 재사용)
                try:
                    # run_id에서 experiment_id 조회
                    experiment_id = self._get_experiment_id_from_run(version.run_id)
                    
                    # source에서 model_id 추출
                    model_id = self._extract_model_id_from_source(version.source)
                    
                    # update_yaml_models에 기존 파일 정보 전달하여 중복 호출 방지
                    success = self.github_client.update_yaml_models(
                        engine_match,
                        version.run_id, 
                        version.name, 
                        version.version,
                        experiment_id,
                        model_id,
                        existing_file  # 기존 파일 정보 전달
                    )
                    if success:
                        logger.debug(f"GitHub 업데이트 성공: {version.name}:{version.version} (run_id: {version.run_id})")
                        
                        # 새로운 모델인 경우 ArgoCD 프로젝트 생성
                        if ARGO_AUTO_DEPLOY and is_new:
                            try:
                                project_success = self.github_client.create_argo_project()
                                if project_success:
                                    logger.info(f"ArgoCD 프로젝트 생성/업데이트 성공: {ARGOCD_PROJECT_NAME}")
                                    try:
                                        argo_success = self.github_client.add_model_to_argo_application(engine_match, version.name)
                                        if argo_success:
                                            logger.info(f"ArgoCD Application 생성/업데이트 성공: {ARGOCD_PROJECT_NAME} - {version.name}")
                                        else:
                                            logger.error(f"ArgoCD Application 생성 실패: {ARGOCD_PROJECT_NAME} - {version.name}")
                                    except Exception as e:
                                        logger.error(f"ArgoCD Application 생성 중 오류: {ARGOCD_PROJECT_NAME} - {version.name} - {e}")
                                else:
                                    logger.error(f"ArgoCD 프로젝트 생성 실패: {ARGOCD_PROJECT_NAME}")
                            except Exception as e:
                                logger.error(f"ArgoCD 프로젝트 생성 중 오류: {ARGOCD_PROJECT_NAME} - {e}")
                            
                            
                        elif not ARGO_AUTO_DEPLOY:
                            logger.info(f"ARGO_AUTO_DEPLOY가 비활성화되어 {ARGOCD_PROJECT_NAME}의 {version.name}의 ArgoCD 프로젝트 생성을 건너뜁니다.")

                    else:
                        logger.error(f"GitHub 업데이트 실패: {version.name}:{version.version} (run_id: {version.run_id})")
                except Exception as e:
                    logger.error(f"GitHub 업데이트 중 오류: {e}")
                
                if EVALUATION_ENABLED:
                    try:
                        logger.info(f"모델 평가 요청: {version.name}:{version.version} (run_id: {version.run_id})")
                        self._request_evaluation(version.name, version.version, engine_match)
                    except Exception as e:
                        logger.error(f"모델 평가 요청 실패: {version.name}:{version.version} (run_id: {version.run_id}) - {e}")
                else:
                    logger.info(f"모델 평가 비활성화되어 {version.name}:{version.version} (run_id: {version.run_id})의 평가를 건너뜁니다.")
        
        except Exception as e:
            logger.error(f"새로운 모델 버전 확인 실패: {e}")
        
        return events
    
    def _request_evaluation(self, model_name: str, version: str, engine_type: str) -> bool:
        """모델 평가 요청"""
        model_name = model_name.lower().replace("_", "-").replace(".", "-")
        payload = {
            "model_name": f"{engine_type}-{model_name}-{version}",
            "inference_engine_url": f"http://{engine_type}-{model_name}.{ENGINE_NAMESPACE}:{ENGINE_PORT}"
        }
        logger.debug(f"모델 평가 요청 페이로드: {payload}")
        response = requests.post(BENCHMARK_EVAL_URL, json=payload)
        logger.debug(f"모델 평가 요청 응답: {response.json()}")
        return response.status_code == 200

    def poll_once(self) -> PollingResult:
        """한 번의 폴링 실행"""
        logger.info("폴링 시작...")
        
        all_events = []
        errors = []
        
        # 1. 새로운 모델 확인
        try:
            new_model_events = self._check_new_models()
            all_events.extend(new_model_events)
        except Exception as e:
            errors.append(f"새로운 모델 확인 실패: {str(e)}")
        
        # 2. 새로운 모델 버전 확인
        try:
            new_version_events = self._check_new_versions()
            all_events.extend(new_version_events)
        except Exception as e:
            errors.append(f"새로운 모델 버전 확인 실패: {str(e)}")
        

        
        # 3. 결과 생성
        current_time = datetime.now()
        
        result = PollingResult(
            events_count=len(all_events),
            github_updates=len([e for e in all_events if e.event_type == "model_version_created"]),
            success=len(errors) == 0,
            errors=errors,
            timestamp=current_time
        )

        logger.info(f"폴링 완료: {result.events_count}개 이벤트, {result.github_updates}개 GitHub 업데이트 성공")
        
        return result
    
    def start_polling(self):
        """폴링 시작 (백그라운드 스레드)"""
        if self._polling_thread and self._polling_thread.is_alive():
            logger.warning("폴링이 이미 실행 중입니다.")
            return
        
        logger.info(f"MLflow 폴링 시작 (간격: {self.polling_interval}초)")
        
        # GitHub 연결 테스트
        if self.github_client:
            if not self.github_client.test_connection():
                logger.error("GitHub 연결 테스트 실패")
                return
        
        # 폴링 스레드 시작
        self._stop_event.clear()
        self._polling_thread = threading.Thread(target=self._polling_worker, daemon=True)
        self._polling_thread.start()
    
    def _polling_worker(self):
        """폴링 워커 (백그라운드 스레드에서 실행)"""
        try:
            while not self._stop_event.is_set():
                try:
                    result = self.poll_once()
                    if not result.success:
                        logger.warning(f"폴링 중 오류 발생: {result.errors}")
                except Exception as e:
                    logger.error(f"폴링 중 예외 발생: {e}")
                
                # 인터럽트 가능한 sleep
                if self._stop_event.wait(timeout=self.polling_interval):
                    break
                
        except Exception as e:
            logger.error(f"폴링 서비스 오류: {e}")
        finally:
            logger.info("폴링 워커 종료")
    
    def stop_polling(self):
        """폴링 중지"""
        logger.info("폴링 중지 요청")
        
        if self._polling_thread and self._polling_thread.is_alive():
            self._stop_event.set()
            self._polling_thread.join(timeout=5)
            if self._polling_thread.is_alive():
                logger.warning("폴링 스레드가 정상적으로 종료되지 않았습니다.")
            else:
                logger.info("폴링 스레드 종료 완료")
        else:
            logger.info("폴링이 실행 중이 아닙니다.")
    
    def test_connections(self) -> Dict[str, bool]:
        """모든 연결 테스트"""
        results = {}
        
        # MLflow 연결 테스트
        try:
            self.mlflow_client.search_registered_models()
            results['mlflow'] = True
            logger.info("MLflow 연결 테스트 성공")
        except Exception as e:
            results['mlflow'] = False
            logger.error(f"MLflow 연결 테스트 실패: {e}")
        
        # GitHub 연결 테스트
        if self.github_client:
            results['github'] = self.github_client.test_connection()
        else:
            results['github'] = None
        

        
        return results 