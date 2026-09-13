package com.example.roman.service;

import com.example.roman.api.EvaluatorApi;
import com.example.roman.api.model.EvaluationRequest;
import com.example.roman.api.model.EvaluationResponse;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.RestController;

/**
 * Implements the interface generated from roman-service.yaml; the document owns the contract.
 */
@RestController
public class EvaluateController implements EvaluatorApi {

    private final RomanEvaluationService service;

    public EvaluateController(RomanEvaluationService service) {
        this.service = service;
    }

    @Override
    public ResponseEntity<EvaluationResponse> evaluateRoman(EvaluationRequest evaluationRequest) {
        int value = service.evaluate(evaluationRequest.getRoman());
        return ResponseEntity.ok(new EvaluationResponse(value));
    }

    @Override
    public ResponseEntity<Void> evaluateHealth() {
        return ResponseEntity.ok().build();
    }
}
