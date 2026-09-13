package com.example.roman.service;

import com.example.roman.RomanServiceApplication;
import com.example.roman.api.model.EvaluationResponse;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

@SpringBootTest(classes = RomanServiceApplication.class,
        webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class RomanServiceIT {

    @Autowired
    private TestRestTemplate rest;

    @LocalServerPort
    private int port;

    private String url(String path) {
        return "http://localhost:" + port + path;
    }

    private HttpEntity<String> json(String body) {
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        return new HttpEntity<>(body, headers);
    }

    @Test
    void evaluateAnswersOverARealPort() {
        ResponseEntity<EvaluationResponse> response = rest.postForEntity(
                url("/evaluate"), json("{\"roman\":\"XIV\"}"), EvaluationResponse.class);
        assertEquals(HttpStatus.OK, response.getStatusCode());
        assertNotNull(response.getBody());
        assertEquals(14, response.getBody().getValue().intValue());
    }

    @Test
    void aNonCanonicalNumeralIsAClientError() {
        ResponseEntity<String> response = rest.postForEntity(
                url("/evaluate"), json("{\"roman\":\"IIII\"}"), String.class);
        assertEquals(HttpStatus.BAD_REQUEST, response.getStatusCode());
    }

    @Test
    void aMalformedBodyIsAClientError() {
        ResponseEntity<String> response = rest.postForEntity(
                url("/evaluate"), json("not json"), String.class);
        assertTrue(response.getStatusCode().is4xxClientError(),
                "a malformed body must be a client error, was " + response.getStatusCode());
    }

    @Test
    void healthAnswers() {
        ResponseEntity<String> response = rest.getForEntity(url("/evaluate/health"), String.class);
        assertEquals(HttpStatus.OK, response.getStatusCode());
    }
}
