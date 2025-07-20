from abc import ABC, abstractmethod
from typing import Dict, Any
from datetime import datetime


class BaseYAMLProcessor(ABC):
    """YAML 처리를 위한 기본 추상 클래스"""
    
    def __init__(self, benchmark_eval_url: str):
        """
        Args:
            benchmark_eval_url: Benchmark evaluation service URL
        """
        self.benchmark_eval_url = benchmark_eval_url
    
    @abstractmethod
    def process_yaml_data(self, yaml_data: Dict[str, Any], model_name: str, 
                         run_id: str, experiment_id: str, model_id: str, 
                         version: str) -> Dict[str, Any]:
        """
        엔진별 YAML 데이터 처리
        
        Args:
            yaml_data: 기본 YAML 데이터
            model_name: 모델 이름
            run_id: MLflow 실행 ID
            experiment_id: MLflow 실험 ID
            model_id: 모델 ID
            version: 모델 버전
            
        Returns:
            처리된 YAML 데이터
        """
        pass
    
    @abstractmethod
    def get_application_name(self, model_name: str) -> str:
        """
        ArgoCD Application 이름 생성
        
        Args:
            model_name: 모델 이름
            
        Returns:
            Application 이름
        """
        pass
    
    def _get_model_name_k8s(self, model_name: str) -> str:
        """모델명을 k8s 호환 형태로 변환"""
        return model_name.replace("/", "-").replace(".", "-").replace("_", "-").lower()
    
    def _update_global_section(self, yaml_data: Dict[str, Any], model_name: str,
                              run_id: str, experiment_id: str, model_id: str,
                              version: str) -> None:
        """Global 섹션 업데이트 (공통 로직)"""
        if 'global' not in yaml_data:
            yaml_data['global'] = {}
            
        yaml_data['global']['experimentId'] = experiment_id
        yaml_data['global']['runid'] = run_id
        yaml_data['global']['modelid'] = model_id
        yaml_data['global']['timestamp'] = datetime.now().strftime("%Y%m%d-%H%M%S")
        yaml_data['global']['modelName'] = model_name
        yaml_data['global']['modelVersion'] = version 