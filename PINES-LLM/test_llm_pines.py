"""
Test script for PINES-LLM
Tests the service with sample clinical notes
"""

import httpx
import asyncio
from typing import Dict, Any


# Test cases with expected outcomes
TEST_CASES = [
    {
        "name": "VTE - Positive (DVT confirmed)",
        "text": "Patient with acute DVT left lower extremity confirmed by duplex ultrasound. Started on anticoagulation.",
        "task": "vte_detection",
        "expected_label": 1,
        "expected_score_min": 0.85
    },
    {
        "name": "VTE - Negative (ruled out)",
        "text": "Ultrasound shows no evidence of DVT. Patient doing well.",
        "task": "vte_detection",
        "expected_label": 0,
        "expected_score_min": 0.85
    },
    {
        "name": "VTE - Negative (family history)",
        "text": "Family history significant for DVT in mother at age 55.",
        "task": "vte_detection",
        "expected_label": 0,
        "expected_score_min": 0.80
    },
    {
        "name": "VTE - Positive (PE confirmed)",
        "text": "CT angiography reveals bilateral pulmonary emboli. Patient admitted to ICU.",
        "task": "vte_detection",
        "expected_label": 1,
        "expected_score_min": 0.90
    },
    {
        "name": "Metastasis - Positive",
        "text": "CT scan shows multiple liver metastases consistent with breast primary. Stage IV disease.",
        "task": "metastasis_detection",
        "expected_label": 1,
        "expected_score_min": 0.85
    },
    {
        "name": "Metastasis - Negative",
        "text": "Stage II breast cancer. Lymph nodes negative. No evidence of distant metastases.",
        "task": "metastasis_detection",
        "expected_label": 0,
        "expected_score_min": 0.85
    }
]


async def test_prediction(client: httpx.AsyncClient, test_case: Dict[str, Any]) -> Dict[str, Any]:
    """Test a single prediction"""
    
    print(f"\n{'='*80}")
    print(f"Test: {test_case['name']}")
    print(f"{'='*80}")
    print(f"Note: {test_case['text'][:100]}...")
    
    try:
        response = await client.post(
            "http://localhost:8036/predict",
            json={
                "text": test_case["text"],
                "task": test_case["task"]
            },
            timeout=60.0
        )
        response.raise_for_status()
        result = response.json()
        
        prediction = result["prediction"]
        metadata = result.get("metadata", {})
        
        print(f"\nResults:")
        print(f"  Label: {prediction['label']} (expected: {test_case['expected_label']})")
        print(f"  Score: {prediction['score']:.3f} (expected: >{test_case['expected_score_min']})")
        print(f"  Reasoning: {metadata.get('reasoning', 'N/A')[:200]}")
        print(f"  Latency: {metadata.get('latency_ms', 0)}ms")
        print(f"  Tokens: {metadata.get('tokens_used', 0)}")
        
        # Check if prediction matches expectations
        label_correct = prediction['label'] == test_case['expected_label']
        score_ok = prediction['score'] >= test_case['expected_score_min']
        
        status = "✅ PASS" if (label_correct and score_ok) else "❌ FAIL"
        print(f"\nStatus: {status}")
        
        if not label_correct:
            print(f"  ⚠️  Label mismatch: got {prediction['label']}, expected {test_case['expected_label']}")
        if not score_ok:
            print(f"  ⚠️  Low confidence: {prediction['score']:.3f} < {test_case['expected_score_min']}")
        
        return {
            "name": test_case["name"],
            "passed": label_correct and score_ok,
            "result": result
        }
        
    except Exception as e:
        print(f"\n❌ ERROR: {str(e)}")
        return {
            "name": test_case["name"],
            "passed": False,
            "error": str(e)
        }


async def test_health():
    """Test health check endpoint"""
    print("\n" + "="*80)
    print("Testing Health Check")
    print("="*80)
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get("http://localhost:8036/healthcheck")
            response.raise_for_status()
            result = response.json()
            
            print(f"Status: {result.get('status', 'Unknown')}")
            print(f"Message: {result.get('message', 'N/A')}")
            print(f"Backend Healthy: {result.get('backend_healthy', False)}")
            
            if result.get('status') == 'Healthy':
                print("✅ Health check passed")
                return True
            else:
                print("❌ Service unhealthy")
                return False
                
        except Exception as e:
            print(f"❌ Health check failed: {str(e)}")
            return False


async def test_list_tasks():
    """Test tasks listing endpoint"""
    print("\n" + "="*80)
    print("Listing Available Tasks")
    print("="*80)
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get("http://localhost:8036/tasks")
            response.raise_for_status()
            result = response.json()
            
            print(f"Available tasks:")
            for task in result.get("available_tasks", []):
                print(f"  - {task}")
            print(f"Default task: {result.get('default_task', 'N/A')}")
            print("✅ Tasks retrieved successfully")
            return True
            
        except Exception as e:
            print(f"❌ Failed to retrieve tasks: {str(e)}")
            return False


async def main():
    """Run all tests"""
    print("\n" + "="*80)
    print("PINES-LLM Test Suite")
    print("="*80)
    
    # Check health
    health_ok = await test_health()
    if not health_ok:
        print("\n⚠️  Service not healthy. Please check:")
        print("  1. Is the service running? (python llm_pines.py)")
        print("  2. Is the backend accessible? (Ollama/vLLM)")
        print("  3. Is the model loaded?")
        return
    
    # List tasks
    await test_list_tasks()
    
    # Run prediction tests
    print("\n" + "="*80)
    print("Running Prediction Tests")
    print("="*80)
    
    results = []
    async with httpx.AsyncClient() as client:
        for test_case in TEST_CASES:
            result = await test_prediction(client, test_case)
            results.append(result)
            await asyncio.sleep(0.5)  # Small delay between tests
    
    # Summary
    print("\n" + "="*80)
    print("Test Summary")
    print("="*80)
    
    passed = sum(1 for r in results if r.get("passed", False))
    total = len(results)
    
    print(f"\nTotal: {total}")
    print(f"Passed: {passed} ✅")
    print(f"Failed: {total - passed} ❌")
    print(f"Success Rate: {(passed/total)*100:.1f}%")
    
    if passed == total:
        print("\n🎉 All tests passed!")
    else:
        print("\n⚠️  Some tests failed. Consider:")
        print("  - Using a larger model (e.g., llama3.1:70b)")
        print("  - Adjusting prompts in prompts/ directory")
        print("  - Setting temperature to 0.0 for deterministic output")


if __name__ == "__main__":
    asyncio.run(main())




