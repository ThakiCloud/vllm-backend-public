import logging
from typing import Dict, Any
from base_processor import BaseYAMLProcessor

logger = logging.getLogger(__name__)


class VLLMProcessor(BaseYAMLProcessor):
    """vLLM을 위한 YAML 프로세서"""
    
    def process_yaml_data(self, yaml_data: Dict[str, Any], model_name: str,
                         run_id: str, experiment_id: str, model_id: str,
                         version: str) -> Dict[str, Any]:
        """
        vLLM용 YAML 데이터 처리
        """
        try:
            # Global 섹션 업데이트
            self._update_global_section(yaml_data, model_name, run_id, experiment_id, model_id, version)
            
            # 모델명을 k8s 호환 형태로 변환
            model_name_k8s = self._get_model_name_k8s(model_name)
            
            # vLLM 섹션 처리
            if 'vllm' in yaml_data:
                # vllm.vllm 섹션 처리
                if 'vllm' in yaml_data['vllm']:
                    yaml_data['vllm']['vllm']['evalEndpoint'] = self.benchmark_eval_url
                    yaml_data['vllm']['vllm']['model'] = f"/data/local_models/{model_name_k8s}"
                
                # fullnameOverride 업데이트
                yaml_data['vllm']['fullnameOverride'] = f"vllm-{model_name_k8s}"
                
                # serviceAccount name 업데이트
                if 'serviceAccount' in yaml_data['vllm']:
                    yaml_data['vllm']['serviceAccount']['name'] = f"vllm-{model_name_k8s}-sa"
                    
                logger.debug(f"vLLM YAML 처리 완료: {model_name}")
            else:
                logger.warning(f"YAML에 vllm 섹션이 없습니다: {model_name}")
            
            return yaml_data
            
        except Exception as e:
            logger.error(f"vLLM YAML 처리 중 오류 발생: {e}")
            raise
    
    def get_application_name(self, model_name: str) -> str:
        """
        vLLM ArgoCD Application 이름 생성
        """
        model_name_k8s = self._get_model_name_k8s(model_name)
        return f"vllm-{model_name_k8s}" 