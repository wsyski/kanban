package com.example.roman.service;

import com.example.roman.api.EvaluatorApi;
import java.io.InputStream;
import java.nio.file.Path;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.yaml.snakeyaml.Yaml;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
class EvaluateContractTest {

    @Autowired
    private MockMvc mockMvc;

    @Test
    void evaluateAnswersTheValueTheDocumentDeclares() throws Exception {
        mockMvc.perform(post("/evaluate")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"roman\":\"XIV\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.value").value(14));
    }

    @Test
    void aNonCanonicalNumeralIsAClientError() throws Exception {
        mockMvc.perform(post("/evaluate")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"roman\":\"IIII\"}"))
                .andExpect(status().is4xxClientError());
    }

    @Test
    void aMalformedBodyIsAClientError() throws Exception {
        mockMvc.perform(post("/evaluate")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("not json"))
                .andExpect(status().is4xxClientError());
    }

    @Test
    void healthAnswers() throws Exception {
        mockMvc.perform(get("/evaluate/health"))
                .andExpect(status().isOk());
    }

    @Test
    void theDocumentDeclaresThePathAndTheResponseShape() throws Exception {
        Map<String, Object> document = loadDocument();
        Map<String, Object> paths = map(document.get("paths"));
        assertTrue(paths.containsKey("/evaluate"), "document declares POST /evaluate");
        assertTrue(paths.containsKey("/evaluate/health"), "document declares GET /evaluate/health");

        Map<String, Object> schemas = map(map(document.get("components")).get("schemas"));
        Map<String, Object> response = map(map(schemas.get("EvaluationResponse")).get("properties"));
        assertEquals(Set.of("value"), response.keySet(), "EvaluationResponse declares exactly `value`");
        assertEquals("integer", response.get("value") instanceof Map
                ? map(response.get("value")).get("type") : null);

        Map<String, Object> request = map(map(schemas.get("EvaluationRequest")).get("properties"));
        assertEquals(Set.of("roman"), request.keySet(), "EvaluationRequest declares exactly `roman`");
    }

    @Test
    void theApiInterfaceIsGeneratedBuildOutput() {
        assertNotNull(EvaluatorApi.class.getProtectionDomain().getCodeSource(),
                "EvaluatorApi must be on the classpath");
        assertTrue(Path.of("target/generated-sources/openapi/src/main/java/com/example/roman/api/EvaluatorApi.java")
                        .toFile().exists(),
                "EvaluatorApi must come from the generator, under target/generated-sources/openapi");
        assertFalse(Path.of("src/main/java/com/example/roman/api/EvaluatorApi.java").toFile().exists(),
                "no hand-written EvaluatorApi under src/main/java");
    }

    private Map<String, Object> loadDocument() throws Exception {
        try (InputStream in = getClass().getResourceAsStream("/openapi/roman-service.yaml")) {
            assertNotNull(in, "the OpenAPI document must be on the classpath");
            return map(new Yaml().load(in));
        }
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> map(Object value) {
        return (Map<String, Object>) value;
    }
}
