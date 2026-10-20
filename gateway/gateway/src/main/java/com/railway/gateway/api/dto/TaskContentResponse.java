package com.railway.gateway.api.dto;

import io.swagger.v3.oas.annotations.media.Schema;

import java.util.List;
import java.util.UUID;

@Schema(description = "Generated instruction text for in-browser viewing/editing")
public record TaskContentResponse(
        @Schema(description = "Task ID")
        UUID taskId,

        @Schema(description = "Plain-text instruction body")
        String content,

        @Schema(description = "Station name from generated document")
        String station,

        @Schema(description = "Organization / company name")
        String company,

        @Schema(description = "Document region template key", example = "chita")
        String region,

        @Schema(description = "Tables from sections and appendices, in document order")
        List<TaskContentTable> tables
) {
}
