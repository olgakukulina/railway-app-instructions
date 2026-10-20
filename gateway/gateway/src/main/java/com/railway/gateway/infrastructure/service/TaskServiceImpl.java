package com.railway.gateway.infrastructure.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.railway.gateway.api.dto.CreateTaskResponse;
import com.railway.gateway.api.dto.TaskContentRequest;
import com.railway.gateway.api.dto.TaskContentResponse;
import com.railway.gateway.api.dto.TaskContentTable;
import com.railway.gateway.api.dto.TaskDetailsResponse;
import com.railway.gateway.api.dto.TaskPageResponse;
import com.railway.gateway.api.dto.TaskStatusResponse;
import com.railway.gateway.api.dto.TaskSummaryResponse;
import com.railway.gateway.application.mapper.TaskMapper;
import com.railway.gateway.application.service.TaskService;
import com.railway.gateway.application.validator.FileValidator;
import com.railway.gateway.domain.entity.Task;
import com.railway.gateway.domain.entity.User;
import com.railway.gateway.domain.enums.TaskStatus;
import com.railway.gateway.domain.event.GeneratedEvent;
import com.railway.gateway.domain.event.ParsedEvent;
import com.railway.gateway.domain.event.TaskCreatedEvent;
import com.railway.gateway.domain.exception.TaskNotFoundException;
import com.railway.gateway.domain.exception.UserNotFoundException;
import com.railway.gateway.domain.exception.application.ResultFileNotFoundException;
import com.railway.gateway.domain.exception.application.TaskNotCompletedException;
import com.railway.gateway.domain.exception.infrastructure.FileDownloadException;
import com.railway.gateway.domain.exception.infrastructure.FileUploadException;
import com.railway.gateway.domain.exception.infrastructure.ObjectNotFoundException;
import com.railway.gateway.domain.repository.TaskRepository;
import com.railway.gateway.domain.repository.UserRepository;
import com.railway.gateway.domain.service.EventPublisher;
import com.railway.gateway.domain.service.MinioService;
import com.railway.gateway.domain.valueobject.BucketType;
import com.railway.gateway.infrastructure.properties.RabbitMqProperties;
import com.railway.gateway.infrastructure.repository.TaskSpecification;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.core.io.InputStreamResource;
import org.springframework.core.io.Resource;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.data.domain.Sort;
import org.springframework.data.jpa.domain.Specification;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.multipart.MultipartFile;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.EnumSet;
import java.util.List;
import java.util.Set;
import java.util.UUID;

@Slf4j
@Service
@RequiredArgsConstructor
public class TaskServiceImpl implements TaskService {

    private static final Set<TaskStatus> CONTENT_READY_STATUSES = EnumSet.of(
            TaskStatus.GENERATED,
            TaskStatus.ASSEMBLING,
            TaskStatus.COMPLETED
    );

    private final TaskRepository taskRepository;
    private final UserRepository userRepository;
    private final MinioService minioService;
    private final EventPublisher eventPublisher;
    private final FileValidator fileValidator;
    private final TaskMapper taskMapper;
    private final RabbitMqProperties rabbitMqProperties;
    private final ObjectMapper objectMapper;

    @Override
    @Transactional
    public CreateTaskResponse createTask(UUID userId, MultipartFile file) {
        log.info("Creating task for user: {}, file: {}", userId, file.getOriginalFilename());

        fileValidator.validate(file);

        User user = userRepository.findById(userId)
                .orElseThrow(() -> new UserNotFoundException(userId));

        String contentType = file.getContentType();
        if (contentType == null || contentType.isBlank()) {
            contentType = "application/octet-stream";
        }
        // safety: DB column is VARCHAR(255)
        if (contentType.length() > 255) {
            contentType = contentType.substring(0, 255);
        }

        Task task = Task.builder()
                .user(user)
                .originalFileName(file.getOriginalFilename())
                .originalFileType(contentType)
                .status(TaskStatus.CREATED)
                .minioObjectName("temp")
                .build();

        task = taskRepository.save(task);

        String objectKey = minioService.generateObjectKey(task.getId(), file.getOriginalFilename());
        task.setMinioObjectName(objectKey);

        try (InputStream inputStream = file.getInputStream()) {
            minioService.upload(
                    BucketType.SOURCE_DOCUMENTS,
                    objectKey,
                    inputStream,
                    file.getSize(),
                    file.getContentType()
            );
        } catch (IOException e) {
            throw new FileUploadException(BucketType.SOURCE_DOCUMENTS, objectKey, e);
        }

        task = taskRepository.save(task);

        TaskCreatedEvent event = new TaskCreatedEvent(
                task.getId(),
                userId,
                file.getOriginalFilename(),
                objectKey
        );
        eventPublisher.publish(event);

        log.info("Task created successfully: taskId={}, userId={}", task.getId(), userId);

        return taskMapper.toCreateTaskResponse(task);
    }

    @Override
    @Transactional(readOnly = true)
    public TaskDetailsResponse getTask(UUID userId, UUID taskId) {
        log.debug("Getting task: taskId={}, userId={}", taskId, userId);

        Task task = taskRepository.findByIdAndUserId(taskId, userId)
                .orElseThrow(() -> new TaskNotFoundException(taskId, userId));

        return taskMapper.toTaskDetailsResponse(task);
    }

    @Override
    @Transactional(readOnly = true)
    public TaskPageResponse getTasks(UUID userId, int page, int size, String sort,
                                     TaskStatus status, LocalDateTime createdFrom, LocalDateTime createdTo) {
        log.debug("Getting tasks: userId={}, page={}, size={}, status={}, createdFrom={}, createdTo={}",
                userId, page, size, status, createdFrom, createdTo);

        if (!userRepository.existsById(userId)) {
            throw new UserNotFoundException(userId);
        }

        Specification<Task> specification = TaskSpecification.filterBy(userId, status, createdFrom, createdTo);
        Pageable pageable = PageRequest.of(page, size, parseSort(sort));

        Page<Task> taskPage = taskRepository.findAll(specification, pageable);

        List<TaskSummaryResponse> tasks = taskPage.getContent().stream()
                .map(taskMapper::toTaskSummaryResponse)
                .toList();

        log.debug("Found {} tasks for user: {}", tasks.size(), userId);

        return new TaskPageResponse(
                tasks,
                taskPage.getTotalElements(),
                taskPage.getTotalPages(),
                taskPage.getNumber(),
                taskPage.getSize()
        );
    }

    @Override
    @Transactional(readOnly = true)
    public TaskStatusResponse getTaskStatus(UUID userId, UUID taskId) {
        log.debug("Getting task status: taskId={}, userId={}", taskId, userId);

        Task task = taskRepository.findByIdAndUserId(taskId, userId)
                .orElseThrow(() -> new TaskNotFoundException(taskId, userId));

        return taskMapper.toTaskStatusResponse(task);
    }

    @Override
    @Transactional
    public void deleteTask(UUID userId, UUID taskId) {
        log.info("Deleting task: taskId={}, userId={}", taskId, userId);

        Task task = taskRepository.findByIdAndUserId(taskId, userId)
                .orElseThrow(() -> new TaskNotFoundException(taskId, userId));

        try {
            if (task.getMinioObjectName() != null) {
                minioService.delete(BucketType.SOURCE_DOCUMENTS, task.getMinioObjectName());
            }
            if (task.getParsedContentObjectKey() != null) {
                minioService.delete(BucketType.PARSED_JSON, task.getParsedContentObjectKey());
            }
            if (task.getGeneratedInstructionObjectKey() != null) {
                minioService.delete(BucketType.GENERATED_JSON, task.getGeneratedInstructionObjectKey());
            }
            if (task.getResultMinioObjectName() != null) {
                minioService.delete(BucketType.RESULT_DOCUMENTS, task.getResultMinioObjectName());
            }
        } catch (Exception e) {
            log.warn("Failed to delete files from MinIO for task: {}", taskId, e);
        }

        taskRepository.delete(task);

        log.info("Task deleted successfully: taskId={}, userId={}", taskId, userId);
    }

    @Override
    @Transactional(readOnly = true)
    public Resource downloadTask(UUID userId, UUID taskId) {
        log.info("Downloading task result: taskId={}, userId={}", taskId, userId);

        Task task = taskRepository.findByIdAndUserId(taskId, userId)
                .orElseThrow(() -> new TaskNotFoundException(taskId, userId));

        if (task.getStatus() != TaskStatus.COMPLETED) {
            throw new TaskNotCompletedException(taskId, task.getStatus());
        }

        if (task.getResultMinioObjectName() == null || task.getResultMinioObjectName().isBlank()) {
            throw new ResultFileNotFoundException(taskId);
        }

        try {
            InputStream inputStream = minioService.download(
                    BucketType.RESULT_DOCUMENTS,
                    task.getResultMinioObjectName()
            );

            log.info("Task result downloaded successfully: taskId={}, userId={}", taskId, userId);

            return new InputStreamResource(inputStream);
        } catch (ObjectNotFoundException e) {
            throw new ResultFileNotFoundException(taskId, e);
        }
    }

    @Override
    @Transactional(readOnly = true)
    public TaskContentResponse getTaskContent(UUID userId, UUID taskId) {
        log.info("Getting task content: taskId={}, userId={}", taskId, userId);
        Task task = requireTaskWithGeneratedJson(userId, taskId);
        return readContentFromGeneratedJson(task);
    }

    @Override
    @Transactional
    public TaskContentResponse saveTaskContent(UUID userId, UUID taskId, TaskContentRequest request) {
        log.info("Saving task content: taskId={}, userId={}", taskId, userId);
        Task task = requireTaskWithGeneratedJson(userId, taskId);
        String key = task.getGeneratedInstructionObjectKey();

        try (InputStream inputStream = minioService.download(BucketType.GENERATED_JSON, key)) {
            ObjectNode root = (ObjectNode) objectMapper.readTree(inputStream);
            ArrayNode sections = objectMapper.createArrayNode();
            ObjectNode section = objectMapper.createObjectNode();
            section.put("id", "0001");
            section.put("order", 1);
            section.put("title", "Инструкция");
            section.put("text", request.content());
            sections.add(section);
            root.set("sections", sections);

            byte[] bytes = objectMapper.writerWithDefaultPrettyPrinter().writeValueAsBytes(root);
            minioService.upload(
                    BucketType.GENERATED_JSON,
                    key,
                    new ByteArrayInputStream(bytes),
                    bytes.length,
                    "application/json"
            );
            log.info("Task content saved: taskId={}, bytes={}", taskId, bytes.length);
            return new TaskContentResponse(
                    taskId,
                    request.content(),
                    textOrEmpty(root, "station_name"),
                    textOrEmpty(root, "organization"),
                    textOrEmpty(root, "region"),
                    readTables(root)
            );
        } catch (ObjectNotFoundException e) {
            throw new ResultFileNotFoundException(taskId, e);
        } catch (IOException e) {
            throw new FileDownloadException(BucketType.GENERATED_JSON, key, e);
        }
    }

    private Task requireTaskWithGeneratedJson(UUID userId, UUID taskId) {
        Task task = taskRepository.findByIdAndUserId(taskId, userId)
                .orElseThrow(() -> new TaskNotFoundException(taskId, userId));

        if (!CONTENT_READY_STATUSES.contains(task.getStatus())) {
            throw new TaskNotCompletedException(taskId, task.getStatus());
        }
        if (task.getGeneratedInstructionObjectKey() == null || task.getGeneratedInstructionObjectKey().isBlank()) {
            throw new ResultFileNotFoundException(taskId);
        }
        return task;
    }

    private TaskContentResponse readContentFromGeneratedJson(Task task) {
        String key = task.getGeneratedInstructionObjectKey();
        try (InputStream inputStream = minioService.download(BucketType.GENERATED_JSON, key)) {
            JsonNode root = objectMapper.readTree(inputStream);
            List<String> parts = new ArrayList<>();
            JsonNode sections = root.path("sections");
            if (sections.isArray()) {
                for (JsonNode section : sections) {
                    String title = section.path("title").asText("").trim();
                    String text = section.path("text").asText("").trim();
                    if (!title.isEmpty()) {
                        parts.add(title);
                    }
                    if (!text.isEmpty()) {
                        parts.add(text);
                    }
                }
            }
            String content = String.join("\n\n", parts).trim();
            if (content.isEmpty()) {
                content = objectMapper.writerWithDefaultPrettyPrinter().writeValueAsString(root);
            }
            return new TaskContentResponse(
                    task.getId(),
                    content,
                    textOrEmpty(root, "station_name"),
                    textOrEmpty(root, "organization"),
                    textOrEmpty(root, "region"),
                    readTables(root)
            );
        } catch (ObjectNotFoundException e) {
            throw new ResultFileNotFoundException(task.getId(), e);
        } catch (IOException e) {
            throw new FileDownloadException(BucketType.GENERATED_JSON, key, e);
        }
    }

    /** sections[].tables + table-приложения; номер приложения считаем среди всех appendices, как assembler. */
    private static List<TaskContentTable> readTables(JsonNode root) {
        List<TaskContentTable> tables = new ArrayList<>();
        for (JsonNode section : root.path("sections")) {
            for (JsonNode table : section.path("tables")) {
                addTable(tables, table.path("title").asText(""), table);
            }
        }
        int number = 0;
        for (JsonNode appendix : root.path("appendices")) {
            number++;
            if ("table".equals(appendix.path("type").asText())) {
                addTable(tables, "Приложение " + number + ". " + appendix.path("title").asText(""), appendix.path("table"));
            }
        }
        return tables;
    }

    private static void addTable(List<TaskContentTable> tables, String title, JsonNode table) {
        List<List<String>> rows = new ArrayList<>();
        for (JsonNode row : table.path("rows")) {
            rows.add(cells(row));
        }
        if (!rows.isEmpty()) {
            tables.add(new TaskContentTable(title.trim(), cells(table.path("headers")), rows));
        }
    }

    private static List<String> cells(JsonNode array) {
        List<String> cells = new ArrayList<>();
        for (JsonNode cell : array) {
            cells.add(cell.isNull() ? "" : cell.asText(""));
        }
        return cells;
    }

    private static String textOrEmpty(JsonNode root, String field) {
        JsonNode node = root.get(field);
        return node == null || node.isNull() ? "" : node.asText("");
    }

    @Override
    @Transactional
    public void updateStatusToParsing(UUID taskId) {
        Task task = taskRepository.findById(taskId).orElse(null);

        if (task == null) {
            log.warn("Task not found for PARSING_STARTED event: taskId={}", taskId);
            return;
        }

        TaskStatus oldStatus = task.getStatus();
        task.setStatus(TaskStatus.PARSING);
        taskRepository.save(task);

        log.info("Task status updated: taskId={}, oldStatus={}, newStatus=PARSING", taskId, oldStatus);
    }

    @Override
    @Transactional
    public void markParsed(UUID taskId, String parsedContentObjectKey) {
        Task task = taskRepository.findById(taskId).orElse(null);

        if (task == null) {
            log.warn("Task not found for PARSED event: taskId={}", taskId);
            return;
        }

        TaskStatus oldStatus = task.getStatus();
        task.setStatus(TaskStatus.PARSED);
        if (parsedContentObjectKey != null && !parsedContentObjectKey.isBlank()) {
            task.setParsedContentObjectKey(parsedContentObjectKey);
        }
        taskRepository.save(task);

        log.info("Task status updated: taskId={}, oldStatus={}, newStatus=PARSED", taskId, oldStatus);

        // Запускаем следующий этап пайплайна: AI Service
        ParsedEvent aiWorkEvent = new ParsedEvent(taskId, parsedContentObjectKey);
        eventPublisher.publishToDocumentExchange(
                aiWorkEvent,
                rabbitMqProperties.getRoutingKey().getAiAnalyze()
        );
        log.info("Dispatched AI work: taskId={}, routingKey={}", taskId,
                rabbitMqProperties.getRoutingKey().getAiAnalyze());
    }

    @Override
    @Transactional
    public void updateStatusToGenerating(UUID taskId) {
        Task task = taskRepository.findById(taskId).orElse(null);

        if (task == null) {
            log.warn("Task not found for GENERATING_STARTED event: taskId={}", taskId);
            return;
        }

        TaskStatus oldStatus = task.getStatus();
        task.setStatus(TaskStatus.GENERATING);
        taskRepository.save(task);

        log.info("Task status updated: taskId={}, oldStatus={}, newStatus=GENERATING", taskId, oldStatus);
    }

    @Override
    @Transactional
    public void markGenerated(UUID taskId, String generatedInstructionObjectKey) {
        Task task = taskRepository.findById(taskId).orElse(null);

        if (task == null) {
            log.warn("Task not found for GENERATED event: taskId={}", taskId);
            return;
        }

        TaskStatus oldStatus = task.getStatus();
        task.setStatus(TaskStatus.GENERATED);
        if (generatedInstructionObjectKey != null && !generatedInstructionObjectKey.isBlank()) {
            task.setGeneratedInstructionObjectKey(generatedInstructionObjectKey);
        }
        taskRepository.save(task);

        log.info("Task status updated: taskId={}, oldStatus={}, newStatus=GENERATED", taskId, oldStatus);

        // Запускаем следующий этап пайплайна: Assembler Service
        GeneratedEvent assembleWorkEvent = new GeneratedEvent(taskId, generatedInstructionObjectKey);
        eventPublisher.publishToDocumentExchange(
                assembleWorkEvent,
                rabbitMqProperties.getRoutingKey().getAssembleDocument()
        );
        log.info("Dispatched Assembler work: taskId={}, routingKey={}", taskId,
                rabbitMqProperties.getRoutingKey().getAssembleDocument());
    }

    @Override
    @Transactional
    public void updateStatusToAssembling(UUID taskId) {
        Task task = taskRepository.findById(taskId).orElse(null);

        if (task == null) {
            log.warn("Task not found for ASSEMBLING_STARTED event: taskId={}", taskId);
            return;
        }

        TaskStatus oldStatus = task.getStatus();
        task.setStatus(TaskStatus.ASSEMBLING);
        taskRepository.save(task);

        log.info("Task status updated: taskId={}, oldStatus={}, newStatus=ASSEMBLING", taskId, oldStatus);
    }

    @Override
    @Transactional
    public void markCompleted(UUID taskId, String resultMinioObjectName) {
        Task task = taskRepository.findById(taskId).orElse(null);

        if (task == null) {
            log.warn("Task not found for COMPLETED event: taskId={}", taskId);
            return;
        }

        TaskStatus oldStatus = task.getStatus();
        task.setStatus(TaskStatus.COMPLETED);
        task.setResultMinioObjectName(resultMinioObjectName);
        taskRepository.save(task);

        log.info("Task status updated: taskId={}, oldStatus={}, newStatus=COMPLETED", taskId, oldStatus);
    }

    @Override
    @Transactional
    public void markFailed(UUID taskId, String errorMessage) {
        Task task = taskRepository.findById(taskId).orElse(null);

        if (task == null) {
            log.warn("Task not found for FAILED event: taskId={}", taskId);
            return;
        }

        TaskStatus oldStatus = task.getStatus();
        task.setStatus(TaskStatus.FAILED);
        task.setErrorMessage(errorMessage);
        taskRepository.save(task);

        log.info("Task status updated: taskId={}, oldStatus={}, newStatus=FAILED, error={}",
                taskId, oldStatus, errorMessage);
    }

    private Sort parseSort(String sort) {
        if (sort == null || sort.isBlank()) {
            return Sort.by(Sort.Direction.DESC, "createdAt");
        }

        String[] parts = sort.split(",");
        Sort.Direction direction = Sort.Direction.ASC;
        String property = "createdAt";

        if (parts.length >= 1) {
            property = parts[0].trim();
        }
        if (parts.length >= 2 && parts[1].trim().equalsIgnoreCase("desc")) {
            direction = Sort.Direction.DESC;
        }

        return Sort.by(direction, property);
    }
}