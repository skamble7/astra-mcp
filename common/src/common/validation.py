"""Pydantic helpers and validation utilities."""

from typing import Any, Dict, List, Optional, Type, Union

try:
    from pydantic import BaseModel, Field, validator, ValidationError as PydanticValidationError
    from pydantic.fields import FieldInfo
    _HAS_PYDANTIC = True
except ImportError:
    BaseModel = None
    Field = None
    validator = None
    PydanticValidationError = Exception
    FieldInfo = None
    _HAS_PYDANTIC = False

from .logging import get_logger

logger = get_logger(__name__)


class ValidationError(Exception):
    """Custom validation error for non-Pydantic environments."""
    pass


def create_field(
    default: Any = None,
    *,
    description: Optional[str] = None,
    example: Optional[Any] = None,
    **kwargs: Any
) -> Any:
    """Create a field descriptor compatible with or without Pydantic.
    
    Args:
        default: Default value
        description: Field description
        example: Example value
        **kwargs: Additional field parameters
        
    Returns:
        Field descriptor or default value
    """
    if Field is not None:
        return Field(default, description=description, example=example, **kwargs)
    else:
        # Fallback for environments without Pydantic
        return default


def validate_model_data(
    model_class: Type[Any],
    data: Dict[str, Any]
) -> Any:
    """Validate data against a model class.
    
    Args:
        model_class: Pydantic model class
        data: Data to validate
        
    Returns:
        Validated model instance
        
    Raises:
        ValidationError: If validation fails
    """
    if not _HAS_PYDANTIC or not BaseModel or not issubclass(model_class, BaseModel):
        raise ValidationError("Pydantic is required for model validation")
    
    try:
        return model_class(**data)
    except PydanticValidationError as e:
        logger.error("Model validation failed", model=model_class.__name__, errors=e.errors())
        raise ValidationError(f"Validation failed for {model_class.__name__}: {e}")


def model_to_dict(
    model: Any,
    exclude_none: bool = True,
    by_alias: bool = True
) -> Dict[str, Any]:
    """Convert a Pydantic model to a dictionary.
    
    Args:
        model: Pydantic model instance
        exclude_none: Whether to exclude None values
        by_alias: Whether to use field aliases
        
    Returns:
        Model as dictionary
    """
    if not _HAS_PYDANTIC or not BaseModel or not isinstance(model, BaseModel):
        raise ValidationError("Input must be a Pydantic model instance")
    
    return model.dict(exclude_none=exclude_none, by_alias=by_alias)


def validate_json_data(
    data: Union[str, Dict[str, Any]],
    model_class: Type[Any]
) -> Any:
    """Validate JSON data against a model class.
    
    Args:
        data: JSON string or dictionary
        model_class: Pydantic model class
        
    Returns:
        Validated model instance
        
    Raises:
        ValidationError: If validation fails
    """
    if isinstance(data, str):
        try:
            import json
            parsed_data = json.loads(data)
        except json.JSONDecodeError as e:
            raise ValidationError(f"Invalid JSON: {e}")
    else:
        parsed_data = data
    
    return validate_model_data(model_class, parsed_data)


def create_error_response(
    errors: List[Dict[str, Any]],
    request_id: Optional[str] = None
) -> Dict[str, Any]:
    """Create a standardized error response.
    
    Args:
        errors: List of error dictionaries
        request_id: Request ID for the response
        
    Returns:
        Error response dictionary
    """
    return {
        "jsonrpc": "2.0",
        "error": {
            "code": -32602,
            "message": "Invalid params",
            "data": {
                "validation_errors": errors
            }
        },
        "id": request_id
    }


def safe_get_field_value(
    model: Any,
    field_name: str,
    default: Any = None
) -> Any:
    """Safely get a field value from a Pydantic model.
    
    Args:
        model: Pydantic model instance
        field_name: Name of the field to retrieve
        default: Default value if field doesn't exist
        
    Returns:
        Field value or default
    """
    try:
        return getattr(model, field_name, default)
    except AttributeError:
        return default


def merge_model_data(
    base_data: Dict[str, Any],
    override_data: Dict[str, Any]
) -> Dict[str, Any]:
    """Merge two dictionaries for model creation.
    
    Args:
        base_data: Base data dictionary
        override_data: Override data dictionary
        
    Returns:
        Merged data dictionary
    """
    merged = base_data.copy()
    merged.update(override_data)
    return merged


class BaseValidatedModel:
    """Base class for models when Pydantic is not available."""
    
    def __init__(self, **data: Any):
        for key, value in data.items():
            setattr(self, key, value)
    
    def dict(self, exclude_none: bool = True, by_alias: bool = True) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = {}
        for key, value in self.__dict__.items():
            if exclude_none and value is None:
                continue
            result[key] = value
        return result
    
    def json(self, **kwargs: Any) -> str:
        """Convert to JSON string."""
        import json
        return json.dumps(self.dict(**kwargs))


def get_model_base_class() -> Type:
    """Get the appropriate base class for models.
    
    Returns:
        Pydantic BaseModel if available, otherwise BaseValidatedModel
    """
    return BaseModel if BaseModel is not None else BaseValidatedModel