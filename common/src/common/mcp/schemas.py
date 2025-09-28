"""JSON Schema helpers for MCP tools and resources."""

import json
from pathlib import Path
from typing import Any, Dict, Optional, Union

try:
    import jsonschema
    from jsonschema import validate, ValidationError as JSONSchemaValidationError
except ImportError:
    jsonschema = None
    validate = None
    JSONSchemaValidationError = Exception

from ..logging import get_logger

logger = get_logger(__name__)


class SchemaError(Exception):
    """Exception for schema-related errors."""
    pass


def load_json_schema(schema_path: Union[str, Path]) -> Dict[str, Any]:
    """Load a JSON schema from a file.
    
    Args:
        schema_path: Path to the JSON schema file
        
    Returns:
        Loaded schema dictionary
        
    Raises:
        SchemaError: If schema cannot be loaded or parsed
    """
    path = Path(schema_path)
    
    if not path.exists():
        raise SchemaError(f"Schema file not found: {schema_path}")
    
    if not path.is_file():
        raise SchemaError(f"Schema path is not a file: {schema_path}")
    
    try:
        with open(path, 'r', encoding='utf-8') as f:
            schema = json.load(f)
        
        logger.debug("Loaded JSON schema", path=str(path))
        return schema
        
    except json.JSONDecodeError as e:
        raise SchemaError(f"Invalid JSON in schema file {schema_path}: {e}")
    except Exception as e:
        raise SchemaError(f"Error loading schema file {schema_path}: {e}")


def validate_against_schema(
    data: Any,
    schema: Dict[str, Any],
    schema_name: Optional[str] = None
) -> None:
    """Validate data against a JSON schema.
    
    Args:
        data: Data to validate
        schema: JSON schema to validate against
        schema_name: Optional name for the schema (for error messages)
        
    Raises:
        SchemaError: If validation fails or jsonschema is not available
    """
    if not jsonschema:
        raise SchemaError(
            "jsonschema package is required for schema validation. "
            "Install with: pip install jsonschema"
        )
    
    try:
        validate(instance=data, schema=schema)
        logger.debug("Schema validation passed", schema_name=schema_name)
        
    except JSONSchemaValidationError as e:
        schema_desc = f" ({schema_name})" if schema_name else ""
        raise SchemaError(f"Schema{schema_desc} validation failed: {e.message}")
    except Exception as e:
        schema_desc = f" ({schema_name})" if schema_name else ""
        raise SchemaError(f"Schema{schema_desc} validation error: {e}")


def validate_with_schema_file(
    data: Any,
    schema_path: Union[str, Path]
) -> None:
    """Validate data against a schema loaded from a file.
    
    Args:
        data: Data to validate
        schema_path: Path to the JSON schema file
        
    Raises:
        SchemaError: If schema loading or validation fails
    """
    schema = load_json_schema(schema_path)
    schema_name = Path(schema_path).stem
    validate_against_schema(data, schema, schema_name)


def create_tool_schema(
    name: str,
    description: str,
    parameters_schema: Dict[str, Any]
) -> Dict[str, Any]:
    """Create a standard MCP tool schema.
    
    Args:
        name: Tool name
        description: Tool description
        parameters_schema: JSON schema for tool parameters
        
    Returns:
        Complete tool schema
    """
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters_schema
        }
    }


def create_resource_schema(
    uri: str,
    name: str,
    description: Optional[str] = None,
    mime_type: Optional[str] = None
) -> Dict[str, Any]:
    """Create a standard MCP resource schema.
    
    Args:
        uri: Resource URI
        name: Resource name
        description: Optional resource description
        mime_type: Optional MIME type
        
    Returns:
        Complete resource schema
    """
    resource = {
        "uri": uri,
        "name": name,
    }
    
    if description:
        resource["description"] = description
    
    if mime_type:
        resource["mimeType"] = mime_type
    
    return resource


def create_artifact_schema(
    kind: str,
    name: str,
    data: Dict[str, Any],
    description: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Create a standard MCP artifact schema.
    
    Args:
        kind: Artifact kind identifier
        name: Artifact name
        data: Artifact data
        description: Optional artifact description
        metadata: Optional artifact metadata
        
    Returns:
        Complete artifact schema
    """
    artifact = {
        "kind": kind,
        "name": name,
        "data": data,
    }
    
    if description:
        artifact["description"] = description
    
    if metadata:
        artifact["metadata"] = metadata
    
    return artifact


def get_common_parameter_schemas() -> Dict[str, Dict[str, Any]]:
    """Get common parameter schemas for reuse.
    
    Returns:
        Dictionary of common parameter schemas
    """
    return {
        "repo_url": {
            "type": "string",
            "description": "Git repository URL",
            "pattern": r"^(https?|git|ssh)://.*|.*@.*:.*"
        },
        "volume_path": {
            "type": "string",
            "description": "Volume path for storing data",
            "minLength": 1
        },
        "branch": {
            "type": "string",
            "description": "Git branch name",
            "default": "main"
        },
        "depth": {
            "type": "integer",
            "description": "Clone depth (number of commits)",
            "minimum": 1,
            "default": 1
        },
        "timeout": {
            "type": "integer",
            "description": "Operation timeout in seconds",
            "minimum": 1,
            "maximum": 3600,
            "default": 300
        }
    }


def merge_schemas(*schemas: Dict[str, Any]) -> Dict[str, Any]:
    """Merge multiple JSON schemas into one.
    
    Args:
        *schemas: Schemas to merge
        
    Returns:
        Merged schema
    """
    if not schemas:
        return {}
    
    if len(schemas) == 1:
        return schemas[0].copy()
    
    merged = schemas[0].copy()
    
    for schema in schemas[1:]:
        for key, value in schema.items():
            if key == "properties" and key in merged:
                # Merge properties
                merged[key].update(value)
            elif key == "required" and key in merged:
                # Merge required arrays
                merged[key] = list(set(merged[key] + value))
            else:
                # Override other keys
                merged[key] = value
    
    return merged